"""Live edge court: data-driven condor close cost. A mid-marked condor close is cost-net at its REAL
recorded NBBO spread (close_spread_cost_usd) when present, and only falls back to the flat 3%-of-max-loss
haircut when it isn't. Real-fill closes take no haircut. Monkeypatched ledger reads — no disk, no network."""

from app.services.edge_persistence_engine import EdgePersistenceEngine as EP


def _vrp_row(**kw):
    base = {"status": "CLOSED", "strategy": "vrp", "realized_pnl": 100.0, "max_loss_total": 500.0,
            "close_reason": "profit_take", "realized_pnl_basis": "uw_mid"}
    base.update(kw)
    return base


def _only_vrp(row):
    return staticmethod(lambda path: [row] if str(path).endswith("vrp_short_premium_ledger.jsonl") else [])


def _vrp_trade(monkeypatch, row):
    monkeypatch.setattr(EP, "_read", _only_vrp(row))
    trades, _ = EP()._closed_trades()
    return next(t for t in trades if t["sleeve"] == "premium_vrp")


def test_uses_real_spread_cost_when_present(monkeypatch):
    t = _vrp_trade(monkeypatch, _vrp_row(close_spread_cost_usd=73.0))
    assert t["basis"] == "uw_mid_realcost"
    assert abs(t["net"] - (100.0 - 73.0)) < 1e-9        # real $73, NOT flat 3% of 500 = $15


def test_flat_haircut_fallback_when_absent(monkeypatch):
    t = _vrp_trade(monkeypatch, _vrp_row())              # no close_spread_cost_usd
    assert t["basis"] == "uw_mid"
    assert abs(t["net"] - (100.0 - 0.03 * 500.0)) < 1e-9   # flat 3% fallback preserved


def test_real_fill_close_takes_no_haircut(monkeypatch):
    t = _vrp_trade(monkeypatch, _vrp_row(realized_pnl_basis="fills", close_spread_cost_usd=73.0))
    assert t["basis"] == "fills"
    assert abs(t["net"] - 100.0) < 1e-9                  # real fills already paid the spread


def test_legacy_mid_row_gets_real_cost_tag_when_present(monkeypatch):
    t = _vrp_trade(monkeypatch, _vrp_row(realized_pnl_basis="mid", close_spread_cost_usd=40.0))
    assert t["basis"] == "mid_realcost"
    assert abs(t["net"] - (100.0 - 40.0)) < 1e-9


def test_uw_close_value_returns_tuple_when_disabled(monkeypatch):
    # the engine's close-valuer now returns (value, spread); (None, None) when UW pricing is unavailable —
    # so no external call is made here.
    from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V
    import app.services.uw_option_quote_engine as uwq
    monkeypatch.setattr(uwq.UWOptionQuoteEngine, "enabled", lambda self: False)
    assert V()._uw_close_value({"legs": [{"symbol": "X"}]}) == (None, None)
