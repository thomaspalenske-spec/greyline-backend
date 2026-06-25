from fastapi import APIRouter

from app.services.simulation.simulation_ledger_engine import SimulationLedgerEngine

router = APIRouter()


@router.get("/simulation-ledger-summary")
def simulation_ledger_summary():
    return SimulationLedgerEngine().summary()


@router.get("/simulation-ledger")
def simulation_ledger(limit: int = 100):
    return {
        "engine": "SimulationLedgerRoute",
        "limit": limit,
        "records": SimulationLedgerEngine().load(limit=limit),
        "status": "SIMULATION_LEDGER_READY",
    }
