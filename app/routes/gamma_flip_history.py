"""Gamma-flip-vs-spot trend for the index-condor factor proxies — engine records, this only renders."""

from fastapi import APIRouter

from app.services.gamma_flip_history_engine import GammaFlipHistoryEngine

router = APIRouter()


@router.get("/gamma-flip-history")
def gamma_flip_history(symbol: str = None, days: int = 20):
    """Per-symbol daily gap = (gamma_flip - spot)/spot, with a CONVERGING/DIVERGING/CROSSED read — so you
    can see whether a below-flip name's regime is warming toward the condor gate or cooling away. Accrues
    forward (UW serves flip live-only)."""
    return GammaFlipHistoryEngine().trend(symbol=symbol, days=days)
