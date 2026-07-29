"""Discipline endpoints: is each sleeve earning (edge), and what does its spread cost (execution)?"""

from fastapi import APIRouter

from app.services.capital_allocator_engine import CapitalAllocatorEngine
from app.services.edge_persistence_engine import EdgePersistenceEngine
from app.services.execution_cost_engine import ExecutionCostEngine

router = APIRouter()


@router.get("/capital-allocator")
def capital_allocator():
    """Evidence-based allocation the book SHOULD have (recommendation only — never auto-applied)."""
    return CapitalAllocatorEngine().recommend()


@router.get("/edge-persistence")
def edge_persistence():
    """Per-sleeve live track record + a decay verdict (honest 'accumulating' until enough history)."""
    return EdgePersistenceEngine().report()


@router.get("/execution-cost")
def execution_cost():
    """Per-sleeve round-trip spread cost (live) — pair with /edge-persistence: cost > edge = retire."""
    return ExecutionCostEngine().profile()


@router.get("/execution-realized")
def execution_realized():
    """REALIZED slippage vs the decision-time mid, per strategy — what we actually paid + fill rate."""
    from app.services.execution_log_engine import ExecutionLogEngine
    return ExecutionLogEngine().realized()


@router.get("/execute-watch")
def execute_watch():
    """Buy opportunities: WATCH ranked by conviction; EXECUTE = meets criteria but blocked (no capital/glitch)."""
    from app.services.execute_watch_engine import ExecuteWatchEngine
    return ExecuteWatchEngine().view()
