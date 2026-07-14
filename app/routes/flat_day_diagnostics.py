from fastapi import APIRouter

from app.services.flat_day_diagnostics_engine import FlatDayDiagnosticsEngine

router = APIRouter()


@router.get("/flat-day-diagnostics")
def flat_day_diagnostics(lookback_cycles: int = 300):
    """Am I flat, and if so why? Names the gate suppressing execution-ready signals."""
    return FlatDayDiagnosticsEngine(lookback_cycles=lookback_cycles).diagnose()
