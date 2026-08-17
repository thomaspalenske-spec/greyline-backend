"""A defined-risk iron condor's realized P&L is mathematically bounded by [-max_loss, +credit]. A value
outside that band means the close fills were mis-read (the SIM atomic-order ExecutionPrice quirk that
manufactured a +$3,185 'fills' realized on a $165-credit / $335-max-loss condor). The guard rejects it."""

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def test_bounds_guard_rejects_fantasy_and_accepts_real():
    v = V()
    ct, ml = 165.0, 335.0        # credit collected, defined max loss
    assert v._realized_in_defined_risk_bounds(3185.0, ct, ml) is False   # the bug: 19x the max gain
    assert v._realized_in_defined_risk_bounds(-210.0, ct, ml) is True    # a real (bounded) loss
    assert v._realized_in_defined_risk_bounds(165.0, ct, ml) is True     # exactly the max gain
    assert v._realized_in_defined_risk_bounds(-335.0, ct, ml) is True    # exactly the max loss
    assert v._realized_in_defined_risk_bounds(-400.0, ct, ml) is False   # worse than defined max loss
    assert v._realized_in_defined_risk_bounds(200.0, ct, ml) is False    # more than the credit collected


def test_bounds_guard_no_block_when_unknown():
    # can't validate without the risk numbers -> must not block a legitimate close
    assert V()._realized_in_defined_risk_bounds(9999.0, None, None) is True
