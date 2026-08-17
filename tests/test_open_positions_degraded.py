"""Open-positions route on a DEGRADED broker read: positions are UNKNOWN, not zero. The route must NOT
ship a real-looking flat book (open_count=0, total_unrealized_pnl=0.0) to any consumer — it nulls the
counts/totals and flags degraded, mirroring account_summary. (Audit finding: degraded-read-as-flat-book.)"""

import app.routes.open_positions as mod


def _view(reads_ok, positions=None):
    return {"reads_ok": reads_ok, "account_mode": "paper",
            "account_label": "TradeStation Paper Trading Account",
            "positions": positions or []}


def test_degraded_read_nulls_counts_not_zero(monkeypatch):
    monkeypatch.setattr(mod, "BrokerAccountViewEngine",
                        lambda: type("V", (), {"snapshot": lambda s: _view(False)})())
    r = mod.open_positions()
    assert r["status"] == "OPEN_POSITIONS_BROKER_READ_DEGRADED"
    assert r["degraded"] is True and r["reads_ok"] is False
    # the flat-book fantasy would be 0 / 0.0 — must be None (UNKNOWN) instead
    for k in ("open_count", "equity_count", "option_count", "total_unrealized_pnl", "total_notional"):
        assert r[k] is None, f"{k} leaked a real-looking value on a degraded read"
    assert r["open_positions"] == []


def test_healthy_read_reports_real_totals(monkeypatch):
    pos = [{"symbol": "GLW", "asset_type": "EQUITY", "quantity": 2, "current_price": 50.0,
            "unrealized_pnl": 10.0, "entry_price": 45.0}]
    monkeypatch.setattr(mod, "BrokerAccountViewEngine",
                        lambda: type("V", (), {"snapshot": lambda s: _view(True, pos)})())
    r = mod.open_positions()
    assert r["status"] == "OPEN_POSITIONS_READY" and r["reads_ok"] is True
    assert r["open_count"] == 1 and r["total_unrealized_pnl"] == 10.0
