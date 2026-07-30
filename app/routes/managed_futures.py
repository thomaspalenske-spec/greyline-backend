"""Managed-futures sleeve — research verdict + live plan. Engines decide, routes render."""

from fastapi import APIRouter

from app.services.managed_futures_engine import ManagedFuturesEngine
from app.services.managed_futures_research_engine import ManagedFuturesResearchEngine
from app.services.managed_futures_shadow_engine import ManagedFuturesShadowEngine

router = APIRouter()


@router.get("/managed-futures-research")
def managed_futures_research():
    """The cost-aware, correlation-explicit backtest behind the GO verdict (analysis only)."""
    return ManagedFuturesResearchEngine().run()


@router.get("/managed-futures")
def managed_futures():
    """Live sleeve status + plan (armed flag, budget, per-asset long/short signal, execution plan)."""
    return ManagedFuturesEngine().status()


@router.get("/managed-futures-shadow")
def managed_futures_shadow():
    """Forward-test of the FULL long/short strategy — hypothetical P&L, live carry-corr vs backtest."""
    return ManagedFuturesShadowEngine().report()
