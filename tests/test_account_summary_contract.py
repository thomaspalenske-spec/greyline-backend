"""Contract the dashboard's account-summary cards depend on: a DEGRADED broker read publishes
`degraded: True` + null money tiles, so the cards show "—" instead of a fantasy all-cash book.
No network — the broker view is monkeypatched.
"""

import app.routes.account_summary as asr


def test_degraded_broker_read_yields_degraded_flag_and_null_money_tiles(monkeypatch):
    monkeypatch.setattr(asr.BrokerAccountViewEngine, "snapshot",
                        lambda self: {"reads_ok": False, "positions": []})
    a = asr.account_summary()
    assert a["degraded"] is True and a["reads_ok"] is False
    for tile in ("total_equity", "cash_on_hand", "buying_power",
                 "deployed_capital", "unrealized_pnl", "total_return_pct"):
        assert a[tile] is None            # null → dashboard renders "—", never a computed 0 / fantasy


def test_healthy_read_populates_money_tiles(monkeypatch):
    monkeypatch.setattr(asr.BrokerAccountViewEngine, "snapshot",
                        lambda self: {"reads_ok": True, "positions": [], "account_label": "TS Paper"})
    a = asr.account_summary()
    assert a.get("degraded") in (None, False)
    assert a["total_equity"] is not None and a["cash_on_hand"] is not None
