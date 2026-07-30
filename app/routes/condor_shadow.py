"""Condor shadow forward-test — VRP/earnings condors built + marked off UW, no orders."""

from fastapi import APIRouter

from app.services.condor_shadow_engine import CondorShadowEngine

router = APIRouter()


@router.get("/condor-shadow")
def condor_shadow():
    """Hypothetical short-premium condor P&L (realized/unrealized), priced off Unusual Whales."""
    return CondorShadowEngine().report()
