from fastapi import APIRouter

from app.services.simulation.simulation_outcome_ledger_engine import SimulationOutcomeLedgerEngine

router = APIRouter()


@router.get("/simulation-outcome-ledger-summary")
def simulation_outcome_ledger_summary():
    return SimulationOutcomeLedgerEngine().summary()


@router.get("/simulation-outcome-ledger")
def simulation_outcome_ledger(limit: int = 100):
    return {
        "engine": "SimulationOutcomeLedgerRoute",
        "limit": limit,
        "records": SimulationOutcomeLedgerEngine().load(limit=limit),
        "status": "SIMULATION_OUTCOME_LEDGER_READY",
    }


@router.post("/simulation-outcome-ledger/clear")
def clear_simulation_outcome_ledger():
    return SimulationOutcomeLedgerEngine().clear()
