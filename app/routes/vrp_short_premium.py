from fastapi import APIRouter

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine

router = APIRouter()


@router.get("/vrp-short-premium/plan")
def vrp_short_premium_plan():
    """Preview the defined-risk iron condors the conditional-VRP strategy would open today on
    rich-IV/non-earnings names. Places nothing. Every position has capped, pre-known max loss."""
    return ConditionalVRPShortPremiumEngine().plan()


@router.get("/vrp-short-premium/positions")
def vrp_short_premium_positions():
    """Manage open condors (dry-run view): take profit at 50% credit, liquidate near expiry,
    hard-stop near the defined max loss."""
    return ConditionalVRPShortPremiumEngine().manage_positions(dry_run=True)


@router.get("/vrp-short-premium/dress-rehearsal")
def vrp_short_premium_dress_rehearsal():
    """READ-ONLY pre-fire trace: builds VRP condors against LIVE UW chains, validates each is a sound
    defined-risk structure, and projects the round-trip into the edge court (premium_vrp). VRP is
    continuous (not event-gated) — the fastest honest path to filling the court's trade gate. Places nothing."""
    return ConditionalVRPShortPremiumEngine().dress_rehearsal()


@router.get("/vrp-short-premium/arm-health")
def vrp_short_premium_arm_health():
    """Arm-health of the VRP sleeve: is the armed sleeve actually booking, or silently idle? Classifies
    the day's state (BOOKED / HELD_CATALYST / FULL / IDLE_NO_BOOK / BOOK_ERROR), reports the current
    catalyst hold reason, open condors, free slots, and the consecutive-idle-session counter that drives
    the stalled-proof-clock alert. READ-ONLY — advances no counters."""
    return ConditionalVRPShortPremiumEngine().arm_health(record=False)


@router.get("/vrp-short-premium/cap-sensitivity")
def vrp_short_premium_cap_sensitivity():
    """READ-ONLY decision tool: how many VRP candidates are tradeable at each per-condor cap level, with
    the %-equity each represents. Builds nothing. Slow (live UW) — on-demand."""
    return ConditionalVRPShortPremiumEngine().cap_sensitivity()


@router.get("/condor-exits")
def condor_exits():
    """Exit levels for every OPEN condor: the profit-take + hard-stop net-buyback targets and the time
    exit (DTE liquidation for VRP, the IV-crush report date for earnings). Read-only; no live quotes."""
    return ConditionalVRPShortPremiumEngine().open_condor_exits()
