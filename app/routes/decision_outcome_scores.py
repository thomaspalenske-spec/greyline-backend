from fastapi import APIRouter
from app.services.decision_outcome_scoring_engine import DecisionOutcomeScoringEngine

router = APIRouter()

@router.get("/decision-outcome-scores")
def decision_outcome_scores():
    return DecisionOutcomeScoringEngine().score()
