from fastapi import APIRouter
from app.services.decision_outcome_tracking_engine import DecisionOutcomeTrackingEngine

router = APIRouter()

@router.get("/decision-outcomes")
def decision_outcomes():
    return DecisionOutcomeTrackingEngine().analyze()
