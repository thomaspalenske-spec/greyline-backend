"""Inspect the adaptive tenor decision — why GreyLine chose a given expiration for a name.

Read-only. Shows every candidate expiration in the band and its market-implied EV components, so
the choice is auditable rather than a black box.
"""

from fastapi import APIRouter

from app.services.adaptive_dte_selection_engine import AdaptiveDTESelectionEngine

router = APIRouter()


@router.get("/adaptive-dte")
def adaptive_dte(symbol: str = "SPY"):
    """Per-name tenor scorecard: candidate expirations, POP/credit/max-loss/EV, and the chosen one."""
    return AdaptiveDTESelectionEngine().scorecard((symbol or "SPY").upper().strip())
