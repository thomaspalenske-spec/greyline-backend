"""Real-vs-with-shadows unrealized P/L snapshot — the real broker book, the hypothetical shadow book, combined."""

from fastapi import APIRouter

from app.services.shadow_inclusive_pnl_engine import ShadowInclusivePnlEngine

router = APIRouter()


@router.get("/shadow-inclusive-pnl")
def shadow_inclusive_pnl():
    """Unrealized P/L with the zero-capital shadows folded in — real book, shadow book (hypothetical), and the
    two combined (% as return on capital-at-work, market-neutral-only netting out the long-only beta baskets)."""
    return ShadowInclusivePnlEngine().snapshot()
