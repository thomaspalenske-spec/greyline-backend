"""Condor shadow forward-test — VRP/earnings condors built + marked off UW, no orders."""

from fastapi import APIRouter

from app.services.condor_shadow_engine import CondorShadowEngine
from app.services.best_condors_engine import BestCondorsEngine

router = APIRouter()


@router.get("/condor-shadow")
def condor_shadow():
    """Hypothetical short-premium condor P&L (realized/unrealized), priced off Unusual Whales."""
    return CondorShadowEngine().report()


@router.get("/best-condors")
def best_condors(limit: int = 12):
    """Ranked list of buildable iron condors (VRP + earnings, off UW). Reads the scheduler's cache."""
    return BestCondorsEngine().cached(limit=limit)
