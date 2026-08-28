"""Construction-time guard for the VRP short-premium ledger: a malformed / negative-credit 'condor' can never
be persisted as a normal OPEN condor (the NRG 260918C50 class — a single-leg, <=$0-credit artifact)."""

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V

_OK = {"symbol": "SPY",
       "legs": [{"symbol": "SPY 260918C700", "action": "SELLTOOPEN"},
                {"symbol": "SPY 260918C705", "action": "BUYTOOPEN"},
                {"symbol": "SPY 260918P600", "action": "SELLTOOPEN"},
                {"symbol": "SPY 260918P595", "action": "BUYTOOPEN"}],
       "credit_total": 196.0, "max_loss_total": 504.0}


def test_wellformed_condor_passes():
    ok, why = V._is_wellformed_condor(_OK)
    assert ok is True and why == ""


def test_dict_form_legs_also_pass():
    d = dict(_OK, legs={"short_call": {"symbol": "a"}, "wing_call": {"symbol": "b"},
                        "short_put": {"symbol": "c"}, "wing_put": {"symbol": "d"}})
    assert V._is_wellformed_condor(d)[0] is True


def test_leg_symbol_as_condor_symbol_is_rejected():
    bad = dict(_OK, symbol="NRG 260918C50")          # the exact bug: a single option leg posing as a condor
    ok, why = V._is_wellformed_condor(bad)
    assert ok is False and "bare underlying" in why


def test_negative_or_zero_credit_is_rejected():
    assert V._is_wellformed_condor(dict(_OK, credit_total=-5))[0] is False
    assert V._is_wellformed_condor(dict(_OK, credit_total=0))[0] is False


def test_incomplete_leg_count_is_rejected():
    assert V._is_wellformed_condor(dict(_OK, legs=[{"symbol": "x"}]))[0] is False
    assert V._is_wellformed_condor(dict(_OK, legs=None))[0] is False


def test_nonpositive_max_loss_is_rejected():
    assert V._is_wellformed_condor(dict(_OK, max_loss_total=0))[0] is False
