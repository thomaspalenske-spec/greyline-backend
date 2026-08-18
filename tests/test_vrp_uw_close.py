"""UW-priced condor closes: the SIM can't price atomic condor closes, so realized P&L is valued off UW
greeks+NBBO (shorts' mid − wings' mid) — the honest source the condor shadow already marks to. Hermetic."""

import app.services.uw_option_quote_engine as uqm
from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V
from app.services.edge_persistence_engine import EdgePersistenceEngine as EP


def _row():
    return {"legs": [
        {"symbol": "SPY_SC", "action": "SELLTOOPEN"},   # short call
        {"symbol": "SPY_SP", "action": "SELLTOOPEN"},   # short put
        {"symbol": "SPY_WC", "action": "BUYTOOPEN"},    # wing call
        {"symbol": "SPY_WP", "action": "BUYTOOPEN"},    # wing put
    ]}


def test_uw_close_value_is_shorts_minus_wings_mid(monkeypatch):
    quotes = {"SPY_SC": (1.0, 1.2), "SPY_SP": (0.9, 1.1), "SPY_WC": (0.3, 0.5), "SPY_WP": (0.2, 0.4)}
    monkeypatch.setattr(uqm.UWOptionQuoteEngine, "enabled", lambda self: True)
    monkeypatch.setattr(uqm.UWOptionQuoteEngine, "quote", lambda self, s: quotes[s])
    cv, spread = V()._uw_close_value(_row())                   # now returns (close_value, close_spread) per share
    # shorts mid 1.1 + 1.0 = 2.1 ; wings mid 0.4 + 0.3 = 0.7 ; cost-to-close = 1.4
    assert abs(cv - 1.4) < 1e-9
    # each leg half-spread = 0.10 (all four are 0.20 wide) → round-trip close spread = 0.40/share
    assert abs(spread - 0.4) < 1e-9


def test_uw_close_value_none_when_uw_disabled(monkeypatch):
    monkeypatch.setattr(uqm.UWOptionQuoteEngine, "enabled", lambda self: False)
    assert V()._uw_close_value(_row()) == (None, None)         # → caller keeps the TS/fill path


def test_uw_close_value_none_on_unquotable_leg(monkeypatch):
    monkeypatch.setattr(uqm.UWOptionQuoteEngine, "enabled", lambda self: True)
    monkeypatch.setattr(uqm.UWOptionQuoteEngine, "quote", lambda self, s: (0.0, 0.0))
    assert V()._uw_close_value(_row()) == (None, None)         # never a fake value off a bad quote


def test_pricing_flag_default_on(monkeypatch):
    monkeypatch.delenv("GREYLINE_VRP_UW_CLOSE_PRICING", raising=False)
    assert V._uw_close_pricing_on() is True                     # UW is the correct source; on by default
    monkeypatch.setenv("GREYLINE_VRP_UW_CLOSE_PRICING", "false")
    assert V._uw_close_pricing_on() is False


def test_court_tags_uw_mid_with_haircut_not_loose_mid(tmp_path, monkeypatch):
    # a UW-priced close is trustworthy but a MID → the court applies the close-spread haircut AND keeps a
    # distinct 'uw_mid' provenance tag (not the loose-legacy 'mid_estimate', not the no-haircut 'fills').
    led = tmp_path / "vrp_ledger.jsonl"
    row = {"status": "CLOSED", "strategy": "vrp", "realized_pnl": 100.0, "realized_pnl_basis": "uw_mid",
           "max_loss_total": 400.0, "credit_total": 120.0, "closed_at": "2026-08-13T00:00:00"}
    led.write_text(__import__("json").dumps(row) + "\n")
    monkeypatch.setattr(EP, "VRP_LEDGER", led)
    trades, _excluded = EP()._closed_trades()
    t = [x for x in trades if x.get("basis") == "uw_mid"]
    assert t, "uw_mid basis must be surfaced with its own provenance tag"
    assert t[0]["net"] < t[0]["gross"]                         # close-spread haircut applied (net < raw realized)
    assert t[0]["gross"] == 100.0
