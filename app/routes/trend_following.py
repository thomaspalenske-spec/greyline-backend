"""Trend-following equity sleeve — live per-asset signal and the backtest proof.

Read-only. `/trend-following` shows each basket asset's 200-DMA state (hold vs cash) and the
whole-share allocation it implies. `/trend-following/proof` runs the multi-asset backtest so the
edge — and its honest limits (risk-adjusted, not raw-return; +0.57 correlated with the carry, not a
clean hedge) — is auditable on real price history through every crisis.
"""

from fastapi import APIRouter

from app.services.trend_following_engine import TrendFollowingEngine
from app.services.trend_following_research_engine import TrendFollowingResearchEngine

router = APIRouter()


@router.get("/trend-following")
def trend_following():
    """Live 200-DMA signal per basket asset + the whole-share long/flat allocation it implies."""
    return TrendFollowingEngine().status()


@router.get("/trend-following/proof")
def trend_following_proof():
    """The backtest: per-asset and equal-weight-basket trend vs buy-and-hold, through 2008/2020/2022."""
    return TrendFollowingResearchEngine().run()
