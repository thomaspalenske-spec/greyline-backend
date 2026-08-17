"""GreyLine must text the SAME alert at most twice, then go silent until it resolves.

A condition that re-asserts every cycle (e.g. 'Mission book OVER-deployed') otherwise pages the operator
indefinitely. ExternalAlertEngine.dispatch now caps sends per fingerprint per EPISODE (MAX_SENDS_PER_FP),
applying even to force=True (force bypasses the spacing cooldown, not the absolute cap). A quiet gap
(no dispatch attempts for EPISODE_RESET_MIN) starts a fresh episode so a genuine recurrence still alerts.
No real texts: the send channels are stubbed.
"""

import json
from datetime import datetime, timedelta

from app.services.external_alert_engine import ExternalAlertEngine as E


def _engine(monkeypatch, tmp_path):
    monkeypatch.delenv("GREYLINE_MAX_ALERT_SENDS", raising=False)     # use the default cap of 2
    monkeypatch.setattr(E, "STATE", tmp_path / "alert_state.json")
    monkeypatch.setattr(E, "_send_imessage", lambda self, t, m, s: {"channel": "imessage", "ok": True})
    monkeypatch.setattr(E, "_send_webhook", lambda self, t, m, s: None)
    monkeypatch.setattr(E, "_send_ntfy", lambda self, t, m, s: None)
    monkeypatch.setattr(E, "_send_macos", lambda self, t, m, s: None)
    return E()


def _fire(e):
    return e.dispatch("Mission book OVER-deployed", "msg", "CRITICAL",
                      fingerprint="BOOK_OVER_DEPLOYED", force=True)


def test_same_alert_texts_at_most_twice(monkeypatch, tmp_path):
    e = _engine(monkeypatch, tmp_path)
    r1, r2, r3, r4 = _fire(e), _fire(e), _fire(e), _fire(e)
    assert r1["reached_off_machine"] is True and r1["episode_send_count"] == 1
    assert r2["reached_off_machine"] is True and r2["episode_send_count"] == 2
    assert r3["status"] == "SUPPRESSED_MAX_SENDS"
    assert r4["status"] == "SUPPRESSED_MAX_SENDS"


def test_distinct_fingerprints_each_send_independently(monkeypatch, tmp_path):
    # daily reports use a UNIQUE fingerprint per day, so the cap never blocks them
    e = _engine(monkeypatch, tmp_path)
    for i in range(4):
        r = e.dispatch(f"Report {i}", "m", "INFO", fingerprint=f"PREOPEN_READY:2026-08-{10+i}", force=True)
        assert r["reached_off_machine"] is True and r["episode_send_count"] == 1


def test_episode_resets_after_quiet_then_alerts_again(monkeypatch, tmp_path):
    e = _engine(monkeypatch, tmp_path)
    _fire(e); _fire(e)
    assert _fire(e)["status"] == "SUPPRESSED_MAX_SENDS"          # capped
    # simulate the condition going quiet longer than the reset window by backdating last_attempt
    st = json.loads((tmp_path / "alert_state.json").read_text())
    st["sends"]["BOOK_OVER_DEPLOYED"]["last_attempt"] = (
        datetime.utcnow() - timedelta(minutes=E.EPISODE_RESET_MIN + 10)).isoformat()
    (tmp_path / "alert_state.json").write_text(json.dumps(st))
    r = _fire(e)
    assert r["reached_off_machine"] is True and r["episode_send_count"] == 1   # fresh episode -> alerts again


def test_env_override_of_the_cap(monkeypatch, tmp_path):
    e = _engine(monkeypatch, tmp_path)
    monkeypatch.setenv("GREYLINE_MAX_ALERT_SENDS", "1")
    r1 = _fire(e)
    r2 = _fire(e)
    assert r1["reached_off_machine"] is True
    assert r2["status"] == "SUPPRESSED_MAX_SENDS"                # cap of 1 honored
