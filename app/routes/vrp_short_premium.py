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
