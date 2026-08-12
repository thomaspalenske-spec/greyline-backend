"""Guard: the dashboard's Open Positions MUST equal the TradeStation account exactly (symbol + qty).

No network — the TradeStation positions read is monkeypatched.
"""

import app.services.tradestation_positions_live_engine as tspl
from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G


def _ts(positions):
    # http_status:200 is REQUIRED — the method skips the comparison (degraded) on any non-200, so a mock
    # without it made every mismatch test hollow-pass on the skip branch (636b8b5 gate, never re-mocked).
    return lambda self: {"http_status": 200, "response_json": {"Positions": positions}}


def _view(*pairs):
    return {"reads_ok": True, "positions": [{"symbol": s, "quantity": q} for s, q in pairs]}


def test_exact_match_passes(monkeypatch):
    monkeypatch.setattr(tspl.TradeStationPositionsLiveEngine, "get_positions",
                        _ts([{"Symbol": "DBC", "Quantity": 12}, {"Symbol": "SGOV", "Quantity": 72}]))
    r = G()._check_open_positions_match_broker(_view(("DBC", 12), ("SGOV", 72)))
    assert r["ok"] is True and r["severity"] == "critical"


def test_position_missing_from_dashboard_is_critical(monkeypatch):
    monkeypatch.setattr(tspl.TradeStationPositionsLiveEngine, "get_positions",
                        _ts([{"Symbol": "DBC", "Quantity": 12}, {"Symbol": "SGOV", "Quantity": 72}]))
    r = G()._check_open_positions_match_broker(_view(("DBC", 12)))     # dashboard dropped SGOV
    assert r["ok"] is False and r["severity"] == "critical"


def test_extra_position_on_dashboard_is_critical(monkeypatch):
    monkeypatch.setattr(tspl.TradeStationPositionsLiveEngine, "get_positions",
                        _ts([{"Symbol": "DBC", "Quantity": 12}]))
    r = G()._check_open_positions_match_broker(_view(("DBC", 12), ("GHOST", 5)))   # phantom on dashboard
    assert r["ok"] is False


def test_wrong_quantity_is_critical(monkeypatch):
    monkeypatch.setattr(tspl.TradeStationPositionsLiveEngine, "get_positions",
                        _ts([{"Symbol": "DBC", "Quantity": 12}]))
    r = G()._check_open_positions_match_broker(_view(("DBC", 10)))     # missized
    assert r["ok"] is False


def test_degraded_read_is_skipped_not_failed():
    # A degraded broker read is SKIPPED, not FAILED: ok:True + degraded_class:True (BROKER_READS_OK owns the
    # degraded signal). Severity stays "critical" as the check's class; degraded_class is what keeps it dark.
    r = G()._check_open_positions_match_broker({"reads_ok": False, "positions": []})
    assert r["ok"] is True and r["degraded_class"] is True
