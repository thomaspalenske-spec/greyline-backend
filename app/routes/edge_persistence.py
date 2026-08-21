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


@router.get("/edge-persistence/proof-maturity")
def edge_proof_maturity():
    """Proof-maturity view: every edge sleeve's distance to its verdict gate + a rough ETA, so the grade's
    only remaining lever (proof accrual) is legible at a glance. Read-only; built on realized_edge()."""
    return EdgePersistenceEngine().proof_maturity()


@router.get("/edge-persistence/proof-milestones")
def edge_proof_milestones():
    """Win-side proof milestones: each sleeve's high-water mark toward its verdict (first close / gate reached /
    PROVEN). Read-only preview of the alert the scheduler pages on — dispatch is suppressed here."""
    return EdgePersistenceEngine().proof_milestone_alert(dispatch=False, record=False)


@router.get("/sleeve-execution-cost")
def sleeve_execution_cost():
    """Per-sleeve round-trip spread cost (live) — pair with /edge-persistence: cost > edge = retire.
    Path renamed from /execution-cost, which collided with the options round-trip endpoint in
    execution_cost.py (registered first, so this handler was permanently shadowed/unreachable)."""
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


@router.get("/opportunity-board")
def opportunity_board():
    """Unified board — equity + option candidates side by side, grouped by edge, sorted by each edge's
    native score (NOT cross-ranked). Never streams chains, so it's safe after hours."""
    from app.services.unified_opportunity_board_engine import UnifiedOpportunityBoardEngine
    return UnifiedOpportunityBoardEngine().board()
