"""Volatility term-structure carry sleeve — live signal, target position, and the backtest proof.

Read-only. `/vol-carry` shows the current term-structure state (contango vs backwardation), the
vol-targeted SVXY position it would hold, and whether the sleeve is armed. `/vol-carry/proof` runs
the 15-year backtest so the edge is auditable — real prices through every crash, honestly costed.
"""

from fastapi import APIRouter

from app.services.vol_term_structure_carry_engine import VolTermStructureCarryEngine
from app.services.vol_term_structure_carry_research_engine import VolTermStructureCarryResearchEngine

router = APIRouter()


@router.get("/vol-carry")
def vol_carry():
    """Live term-structure signal + the vol-targeted, defined-risk SVXY position it implies."""
    return VolTermStructureCarryEngine().status()


@router.get("/vol-carry/proof")
def vol_carry_proof():
    """The backtest: signal-conditioned short-vol vs naive always-short, across 2011-2026 crashes."""
    return VolTermStructureCarryResearchEngine().run()
