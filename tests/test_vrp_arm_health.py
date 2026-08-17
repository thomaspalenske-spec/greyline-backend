"""Guard: the armed VRP sleeve's arm-health classifier + stalled-proof-clock alert.

The whole Edge-proof thesis dies on a stalled clock nobody sees. These tests pin the states that
matter — a benign catalyst hold must stay quiet, a booking error must alarm immediately, and a
multi-session idle stall must alarm regardless of reason. All hermetic: no network, no broker.
"""
import json
from datetime import datetime

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine


def _engine(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_VRP_IDLE_ALERT_DAYS", "3")
    # env_reload must not clobber the arm state during a test
    monkeypatch.setattr("app.services.env_reload.reload_env", lambda *a, **k: None)
    v = ConditionalVRPShortPremiumEngine()
    # redirect ledger + arm-state to tmp so the real data is never touched
    v.LEDGER = tmp_path / "vrp_ledger.jsonl"
    v.ARM_HEALTH_STATE = tmp_path / ".vrp_arm_health.json"
    return v


def test_book_error_alarms_immediately(tmp_path, monkeypatch):
    v = _engine(tmp_path, monkeypatch)
    ah = v.arm_health(open_outcome={"status": "VRP_SHORT_PREMIUM_OPENED",
                                    "opened": [], "errors": [{"e": "reject"}]},
                      is_rth=True, record=False)
    assert ah["day_state"] == "BOOK_ERROR"
    assert ah["should_alert"] is True
    assert ah["severity"] == "CRITICAL"


def test_catalyst_hold_is_benign_no_alert(tmp_path, monkeypatch):
    v = _engine(tmp_path, monkeypatch)
    ah = v.arm_health(open_outcome={"status": "DEFERRED_CATALYST", "events": [{"event": "CPI"}]},
                      is_rth=True, record=False)
    assert ah["day_state"] == "HELD_CATALYST"
    assert ah["should_alert"] is False
    assert ah["deferred"] is True


def test_idle_stall_alarms_after_threshold(tmp_path, monkeypatch):
    v = _engine(tmp_path, monkeypatch)
    held = {"status": "DEFERRED_CATALYST", "events": [{"event": "jobs"}]}
    # three consecutive RTH sessions armed-but-not-booked
    for i, day in enumerate(("2026-01-05", "2026-01-06", "2026-01-07")):
        ah = v.arm_health(open_outcome=held, is_rth=True, record=True,
                          now=datetime.fromisoformat(day + "T15:00:00"))
    assert ah["consecutive_idle_days"] == 3
    assert ah["should_alert"] is True
    assert ah["severity"] == "WARNING"
    assert "stalled" in ah["message"].lower()


def test_record_false_does_not_advance_counter(tmp_path, monkeypatch):
    v = _engine(tmp_path, monkeypatch)
    held = {"status": "DEFERRED_CATALYST"}
    now = datetime.fromisoformat("2026-01-05T15:00:00")
    for _ in range(4):
        ah = v.arm_health(open_outcome=held, is_rth=True, record=False, now=now)
    assert ah["consecutive_idle_days"] == 0  # read-only never mutates


def test_same_day_records_once(tmp_path, monkeypatch):
    v = _engine(tmp_path, monkeypatch)
    held = {"status": "DEFERRED_CATALYST"}
    now = datetime.fromisoformat("2026-01-05T15:00:00")
    for _ in range(5):  # scheduler calls every cycle; counter must advance only once per day
        ah = v.arm_health(open_outcome=held, is_rth=True, record=True, now=now)
    assert ah["consecutive_idle_days"] == 1


def test_booking_resets_idle_counter(tmp_path, monkeypatch):
    v = _engine(tmp_path, monkeypatch)
    held = {"status": "DEFERRED_CATALYST"}
    for day in ("2026-01-05", "2026-01-06"):
        v.arm_health(open_outcome=held, is_rth=True, record=True,
                     now=datetime.fromisoformat(day + "T15:00:00"))
    # a real book lands on day 3 — ground truth is the ledger, so write an OPEN row dated that day
    v.LEDGER.write_text(json.dumps({"symbol": "SPY 260918C500", "status": "OPEN",
                                    "opened_at": "2026-01-07T15:30:00"}) + "\n")
    ah = v.arm_health(open_outcome={"status": "VRP_SHORT_PREMIUM_OPENED", "opened": [{"symbol": "SPY"}]},
                      is_rth=True, record=True, now=datetime.fromisoformat("2026-01-07T16:00:00"))
    assert ah["day_state"] == "BOOKED"
    assert ah["booked_today"] is True
    assert ah["consecutive_idle_days"] == 0


def test_not_recorded_outside_rth(tmp_path, monkeypatch):
    v = _engine(tmp_path, monkeypatch)
    held = {"status": "DEFERRED_CATALYST"}
    for _ in range(4):
        ah = v.arm_health(open_outcome=held, is_rth=False, record=True,
                          now=datetime.fromisoformat("2026-01-05T22:00:00"))
    assert ah["consecutive_idle_days"] == 0  # closed-market cycles must not count as idle sessions


def test_disabled_sleeve_never_alerts(tmp_path, monkeypatch):
    v = _engine(tmp_path, monkeypatch)
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "false")
    ah = v.arm_health(open_outcome={"status": "VRP_SHORT_PREMIUM_OPENED", "errors": [{"e": "x"}]},
                      is_rth=True, record=True)
    assert ah["day_state"] == "DISABLED"
    assert ah["should_alert"] is False
