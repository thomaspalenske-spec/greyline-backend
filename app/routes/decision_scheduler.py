from fastapi import APIRouter
from app.services.decision_scheduler_engine import DecisionSchedulerEngine

router = APIRouter()

@router.get("/scheduler-status")
def scheduler_status():
    return DecisionSchedulerEngine().status()

@router.post("/scheduler-run-once")
def scheduler_run_once():
    return DecisionSchedulerEngine().run_manual_cycle()
