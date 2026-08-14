from fastapi import APIRouter, Query
from app.services.background_scheduler_service import BackgroundSchedulerService

router = APIRouter()

@router.post("/background-scheduler/start")
def background_scheduler_start(interval_seconds: int = Query(30)):
    return BackgroundSchedulerService.start(interval_seconds=interval_seconds)

@router.post("/background-scheduler/stop")
def background_scheduler_stop():
    return BackgroundSchedulerService.stop()

@router.post("/background-scheduler/run-once")
def background_scheduler_run_once():
    return BackgroundSchedulerService.run_once()

@router.get("/background-scheduler/status")
def background_scheduler_status():
    return BackgroundSchedulerService.status()

@router.get("/background-scheduler/cycle-cost-history")
def background_scheduler_cycle_cost_history(limit: int = Query(50)):
    """Per-phase cycle cost over a rolling window (median/p90/max per phase, ranked by median) so a
    persistent hot phase is distinguishable from a one-off spike. The /status card shows only the
    last cycle — this shows the trend."""
    return BackgroundSchedulerService.cycle_cost_history(limit=limit)
