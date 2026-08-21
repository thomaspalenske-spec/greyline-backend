"""Option-implied vol-skew shadow — zero-capital market-neutral forward test of the 25d risk-reversal signal."""

from fastapi import APIRouter

from app.services.iv_skew_shadow_engine import IvSkewShadowEngine

router = APIRouter()


@router.get("/iv-skew-shadow")
def iv_skew_shadow():
    """Long least-put-skewed / short most-put-skewed optionable names (25d risk reversal), settled at live equity
    quotes, judged on the edge court's bar. Zero capital, no orders. Orthogonal to VRP; traded as cheap equity."""
    return IvSkewShadowEngine().report()
