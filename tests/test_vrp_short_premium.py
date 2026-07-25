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
