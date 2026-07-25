"""Defined-risk short-premium strategy. The safety-critical property is that the tail is CAPPED
BY CONSTRUCTION: every position has protective wings, a known max loss, and is sized so that loss
is a small fixed fraction of the book — and a chain without OTM wings yields NO trade, never a
naked strangle."""

import json
import pytest

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine


def _c(side, strike, bid, ask, delta):
    return {"Side": side, "Bid": str(bid), "Ask": str(ask), "Delta": str(delta),
            "DailyOpenInterest": "1000", "Legs": [{"Symbol": f"XYZ 260731{side[0]}{strike}"}]}


def _full_chain():
    # narrow ($2-wide) wings so one condor's defined max loss fits the per-position cap:
    # max width $2 -> $200 - credit $130 = $70 max loss/condor, under the $150 cap
    calls = [_c("Call", 100, 5.0, 5.1, 0.50), _c("Call", 103, 2.5, 2.6, 0.30),
             _c("Call", 105, 1.0, 1.1, 0.20), _c("Call", 107, 0.30, 0.35, 0.07),
             _c("Call", 110, 0.10, 0.12, 0.03)]
    puts = [_c("Put", 100, 5.0, 5.1, -0.50), _c("Put", 97, 2.5, 2.6, -0.30),
            _c("Put", 95, 1.0, 1.1, -0.20), _c("Put", 93, 0.30, 0.35, -0.07),
            _c("Put", 90, 0.10, 0.12, -0.03)]
    return calls + puts


def test_condor_is_defined_risk_with_wings_and_capped_loss():
    e = ConditionalVRPShortPremiumEngine()
    con = e.build_condor("XYZ", _full_chain())
    assert "skip" not in con, con
    # short ~20 delta, wings ~7 delta, both present
    assert con["legs"]["short_call"]["action"] == "SELLTOOPEN"
    assert con["legs"]["wing_call"]["action"] == "BUYTOOPEN"
    assert con["legs"]["wing_call"]["strike"] > con["legs"]["short_call"]["strike"]
    assert con["legs"]["wing_put"]["strike"] < con["legs"]["short_put"]["strike"]
    # max loss is defined and does not exceed the per-position cap
    assert con["max_loss_total"] <= e.MAX_LOSS_PER_POSITION_USD + 1e-6
    assert con["credit_total"] > 0


def test_chain_without_otm_wings_yields_no_trade_not_a_naked_strangle():
    """The exact live constraint: a near-ATM-only chain must SKIP, never sell an uncapped strangle."""
    e = ConditionalVRPShortPremiumEngine()
    near_atm = [_c("Call", 100, 5.0, 5.1, 0.50), _c("Call", 101, 4.5, 4.6, 0.45),
                _c("Put", 100, 5.0, 5.1, -0.50), _c("Put", 99, 4.5, 4.6, -0.45)]
    con = e.build_condor("XYZ", near_atm)
    assert "skip" in con and "wing" in con["skip"].lower()


def test_sizing_caps_max_loss_per_position():
    e = ConditionalVRPShortPremiumEngine()
    con = e.build_condor("XYZ", _full_chain())
    # max loss per condor * qty must never exceed the cap
    assert con["max_loss_per_condor"] * con["quantity"] <= e.MAX_LOSS_PER_POSITION_USD + 1e-6
    assert con["quantity"] >= 1


def test_position_skipped_when_one_condor_exceeds_the_cap(monkeypatch):
    e = ConditionalVRPShortPremiumEngine()
    monkeypatch.setattr(e, "MAX_LOSS_PER_POSITION_USD", 5.0)   # tiny cap no wing can satisfy
    con = e.build_condor("XYZ", _full_chain())
    assert "skip" in con and "cap" in con["skip"]


def test_disabled_by_default_opens_nothing(monkeypatch):
    e = ConditionalVRPShortPremiumEngine()
    assert e.enabled() is False
    monkeypatch.setattr(e, "plan", lambda **k: {"planned": [], "skipped": []})
    r = e.open_positions(dry_run=True)
    assert "DRY RUN" in r.get("note", "")


def test_wings_bought_before_shorts_are_sold(monkeypatch):
    """When arming, the tail cap (wings) must be established before the short legs go live."""
    e = ConditionalVRPShortPremiumEngine()
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    con = e.build_condor("XYZ", _full_chain())
    con.update({"expiration": "2026-07-31", "iv_rank": 0.9, "iv": 0.4})
    monkeypatch.setattr(e, "plan", lambda **k: {"planned": [con], "skipped": []})

    order_seq = []

    class FakeBooking:
        def place_order(self, symbol, qty, action="BUY", **k):
            order_seq.append(action)
            return {"ok": True, "order_id": f"O{len(order_seq)}", "http_status": 200}

    monkeypatch.setattr(e, "_booking", lambda: FakeBooking())
    e.LEDGER = __import__("pathlib").Path(
        __import__("tempfile").mkdtemp()) / "vrp_ledger.jsonl"
    e.open_positions(dry_run=False)
    # the two BUYTOOPEN wing legs must precede the two SELLTOOPEN short legs
    assert order_seq[:2] == ["BUYTOOPEN", "BUYTOOPEN"]
    assert order_seq[2:] == ["SELLTOOPEN", "SELLTOOPEN"]


def test_put_tilt_sells_the_put_nearer_the_money_than_the_call():
    """The overpriced put skew is the richest premium, so the short PUT sits nearer ATM (higher
    delta) than the short CALL — while every leg stays defined-risk with wings."""
    e = ConditionalVRPShortPremiumEngine()
    con = e.build_condor("XYZ", _full_chain())
    assert "skip" not in con, con
    # put delta > call delta => put nearer the money (the tilt), and it's a real tilt not symmetric
    assert con["short_put_delta"] > con["short_call_delta"]
    assert con["put_tilt"] > 0
    # still defined-risk: wings present, max loss capped
    assert con["legs"]["wing_put"]["strike"] < con["legs"]["short_put"]["strike"]
    assert con["max_loss_total"] <= e.MAX_LOSS_PER_POSITION_USD + 1e-6


def test_deltas_are_env_tunable_for_the_premium_vs_crash_dial(monkeypatch):
    e = ConditionalVRPShortPremiumEngine()
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PUT_DELTA", "0.40")
    monkeypatch.setenv("GREYLINE_VRP_SHORT_CALL_DELTA", "0.10")
    assert e._put_delta() == 0.40 and e._call_delta() == 0.10


def test_plan_falls_back_to_symmetric_when_tilt_exceeds_the_cap(monkeypatch):
    """If the put-tilt can't be capped within the per-position cap, plan() must fall back to the
    symmetric condor (capture the premium) rather than skip the name entirely."""
    e = ConditionalVRPShortPremiumEngine()
    monkeypatch.setattr("app.services.conditional_vrp_forward_panel_engine."
                        "ConditionalVRPForwardPanelEngine.rich_iv_candidates",
                        lambda self, names=None: [{"ticker": "XYZ", "iv_rank": 0.9, "iv": 0.3}])
    monkeypatch.setattr(e, "_chain", lambda t: ("2026-07-31", _full_chain()))
    monkeypatch.setattr(e, "_open_symbols", lambda: set())
    monkeypatch.setattr(e, "_open_risk", lambda: 0.0)

    real_build = e.build_condor
    def build(sym, contracts, put_delta=None, call_delta=None):
        # force the tilt (default deltas) to look cap-exceeding; symmetric succeeds
        if put_delta is None or put_delta != e.SHORT_DELTA:
            return {"skip": "no wing keeps one condor's max loss within the per-position cap"}
        return real_build(sym, contracts, put_delta=put_delta, call_delta=call_delta)
    monkeypatch.setattr(e, "build_condor", build)

    r = e.plan(limit=1)
    assert len(r["planned"]) == 1
    assert r["planned"][0].get("tilt_fallback", "").startswith("symmetric")


def test_plan_harvests_richest_skew_first(monkeypatch):
    """Skew-conditioned SELECTION: given several buildable condors, plan picks the richest-skew
    ones (most overpriced premium) at the same defined-risk size — not sizing up, just choosing."""
    e = ConditionalVRPShortPremiumEngine()
    pool = [{"ticker": t, "iv_rank": 0.9, "iv": 0.3} for t in ("LOWSK", "HIGHSK", "MIDSK")]
    monkeypatch.setattr("app.services.conditional_vrp_forward_panel_engine."
                        "ConditionalVRPForwardPanelEngine.rich_iv_candidates",
                        lambda self, names=None: pool)
    monkeypatch.setattr(e, "_chain", lambda t: ("2026-07-31", []))
    monkeypatch.setattr(e, "_open_symbols", lambda: set())
    monkeypatch.setattr(e, "_open_risk", lambda: 0.0)
    skewmap = {"LOWSK": 0.02, "HIGHSK": 0.15, "MIDSK": 0.08}
    monkeypatch.setattr(e, "build_condor", lambda t, c, put_delta=None, call_delta=None: {
        "symbol": t, "quantity": 1, "max_loss_total": 100.0, "credit_total": 20.0,
        "skew": skewmap[t]})

    r = e.plan(limit=2)
    picked = [b["symbol"] for b in r["planned"]]
    assert picked == ["HIGHSK", "MIDSK"], f"expected richest-skew first, got {picked}"
    assert "LOWSK" not in picked   # the flat-skew name is left for the cheaper-premium day
