"""Real-vs-with-shadows unrealized P/L: combine real broker P/L with hypothetical shadow P/L, netting out the
long-only beta baskets for the market-neutral-only view. Hermetic — _real/_shadow_rows monkeypatched."""

from app.services.shadow_inclusive_pnl_engine import ShadowInclusivePnlEngine as S


def test_sum_open_skips_none_and_totals_notional():
    rows = [{"pnl_dollars": 10.0, "entry_close": 100, "contracts": 1},
            {"pnl_dollars": None, "entry_close": 50},                 # unpriced -> skipped
            {"pnl_dollars": -3.0, "entry_close": 20, "contracts": 2}]
    tot, n, notion = S._sum_open(rows)
    assert tot == 7.0 and n == 2
    assert notion == 100 * 100 * 1 + 20 * 100 * 2                     # 10000 + 4000


def test_combines_and_nets_out_beta(monkeypatch):
    monkeypatch.setattr(S, "_real", lambda self: {"ok": True, "unrealized_usd": 10.0,
                                                  "deployed_usd": 1000.0, "unrealized_pct": 1.0, "positions": 5})
    monkeypatch.setattr(S, "_shadow_rows", lambda self: [
        {"shadow": "beta", "style": "long_only_beta", "unrealized_usd": -900.0, "hypothetical_notional_usd": 40000.0, "open_positions": 6},
        {"shadow": "mn", "style": "market_neutral", "unrealized_usd": 50.0, "hypothetical_notional_usd": 10000.0, "open_positions": 8}])
    r = S().snapshot()
    assert r["shadow_total"]["unrealized_usd"] == -850.0
    # ALL: 10 + (-850) = -840 on 1000 + 50000 capital-at-work
    assert r["combined_all_shadows"] == {"unrealized_usd": -840.0, "pct_of_capital_at_work": round(-840/51000*100, 2), "capital_at_work_usd": 51000.0}
    # MARKET-NEUTRAL only (beta netted out): 10 + 50 = 60 on 1000 + 10000
    assert r["combined_market_neutral_only"] == {"unrealized_usd": 60.0, "pct_of_capital_at_work": round(60/11000*100, 2), "capital_at_work_usd": 11000.0}


def test_degraded_real_book_shows_shadows_only(monkeypatch):
    monkeypatch.setattr(S, "_real", lambda self: {"ok": False, "note": "broker read degraded"})
    monkeypatch.setattr(S, "_shadow_rows", lambda self: [
        {"shadow": "x", "style": "market_neutral", "unrealized_usd": 5.0, "hypothetical_notional_usd": 100.0, "open_positions": 1}])
    r = S().snapshot()
    assert "combined_all_shadows" not in r                            # no real book -> no combination
    assert r["shadow_total"]["unrealized_usd"] == 5.0
