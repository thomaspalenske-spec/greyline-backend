"""Mission realized sanity guard: the broker's daily realized is the mission's only realized source, but
the SIM mis-prices atomic condor closes (it once reported +$3,116 on a ~-$225 close, faking +25.8% equity).
A single-cycle delta beyond this small book's plausible P&L is HELD (not banked) + paged, not trusted."""

import json
from app.services.mission_realized_pnl_engine import MissionRealizedPnlEngine as M
import app.services.external_alert_engine as alert


def _wire(monkeypatch, tmp_path, daily):
    monkeypatch.setattr(M, "DIR", tmp_path)
    monkeypatch.setattr(M, "LEDGER", tmp_path / "realized_ledger.jsonl")
    monkeypatch.setattr(M, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(M, "_broker_daily_realized", lambda self: daily)
    monkeypatch.setattr(alert.ExternalAlertEngine, "has_external_channel", lambda self: False)  # no real page


def test_suspect_delta_is_held_not_banked(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, 3116.0)          # SIM fantasy jump, no prior booked_today
    eng = M()
    r = eng.record_from_broker()
    assert r["status"] == "REALIZED_HELD_SUSPECT" and r["booked"] == 0.0
    assert eng.cumulative_realized() == 0.0        # NOTHING banked into equity
    # a held entry is written (audit trail), amount 0 + the held_amount recorded
    rows = [json.loads(l) for l in (tmp_path / "realized_ledger.jsonl").read_text().splitlines() if l.strip()]
    assert rows[-1]["source"] == "broker_realized_held_suspect" and rows[-1]["held_amount"] == 3116.0


def test_normal_delta_still_books(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, -42.0)            # a real, plausible small realized move
    eng = M()
    r = eng.record_from_broker()
    assert r["status"] == "REALIZED_BOOKED" and r["booked"] == -42.0
    assert eng.cumulative_realized() == -42.0


def test_marker_advances_so_suspect_is_not_reprocessed(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, 3116.0)
    M().record_from_broker()                       # held; marker advances to 3116
    # next cycle: daily drifts down $30 (a legit close) -> delta -30, within cap -> books
    monkeypatch.setattr(M, "_broker_daily_realized", lambda self: 3086.0)
    r = M().record_from_broker()
    assert r["status"] == "REALIZED_BOOKED" and r["booked"] == -30.0
