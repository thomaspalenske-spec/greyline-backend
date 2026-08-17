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

@router.get("/cycle-failure-forensics")
def cycle_failure_forensics(limit: int = Query(500)):
    """Classified scheduler cycle failures (error class, failure-locus phase, minutes-to-open) — turns the
    black-box failure COUNT into a diagnosable record. `near_open_failures` are the ones that could have
    missed an armed VRP/momentum entry at the 09:30 open (a lost court-day). Forward-only from first deploy."""
    from app.services.cycle_failure_forensics_engine import CycleFailureForensicsEngine
    return CycleFailureForensicsEngine.summary(limit=limit)
