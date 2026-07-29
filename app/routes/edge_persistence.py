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
