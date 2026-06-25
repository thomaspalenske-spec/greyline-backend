from fastapi import APIRouter

from app.services.simulation.simulation_report_engine import SimulationReportEngine

router = APIRouter()


@router.get("/simulation-report")
def simulation_report(limit: int = 10000):
    return SimulationReportEngine().evaluate(limit=limit)
