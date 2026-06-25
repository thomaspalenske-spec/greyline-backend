from fastapi import APIRouter

from app.services.simulation.simulation_orchestrator_engine import SimulationOrchestratorEngine
from app.services.simulation.simulation_ledger_engine import SimulationLedgerEngine
from app.services.simulation.simulation_outcome_ledger_engine import SimulationOutcomeLedgerEngine

router = APIRouter()


@router.get("/walk-forward-simulation")
def walk_forward_simulation(
    symbol: str = "QQQ",
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
    step_days: int = 1,
    starting_capital: float = 10000,
):
    return SimulationOrchestratorEngine().run(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        step_days=step_days,
        starting_capital=starting_capital,
    )


@router.post("/walk-forward-simulation/run-clean")
def walk_forward_simulation_run_clean(
    symbol: str = "QQQ",
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
    step_days: int = 1,
    starting_capital: float = 10000,
):
    clear_result = SimulationLedgerEngine().clear()
    outcome_clear_result = SimulationOutcomeLedgerEngine().clear()

    run_result = SimulationOrchestratorEngine().run(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        step_days=step_days,
        starting_capital=starting_capital,
    )

    ledger_summary = SimulationLedgerEngine().summary()
    outcome_ledger_summary = SimulationOutcomeLedgerEngine().summary()

    return {
        "clear_result": clear_result,
        "outcome_clear_result": outcome_clear_result,
        "run_result": run_result,
        "ledger_summary": ledger_summary,
        "outcome_ledger_summary": outcome_ledger_summary,
        "status": "WALK_FORWARD_SIMULATION_CLEAN_RUN_COMPLETE",
    }
