from fastapi import APIRouter

from app.services.simulation.walk_forward_simulation_engine import WalkForwardSimulationEngine

router = APIRouter()


@router.get("/walk-forward-simulation")
def walk_forward_simulation(
    symbol: str = "QQQ",
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
    step_days: int = 1,
    starting_capital: float = 10000,
):
    return WalkForwardSimulationEngine().run(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        step_days=step_days,
        starting_capital=starting_capital,
    )
