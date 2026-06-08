from fastapi import APIRouter
from app.services.decision_learning_engine import DecisionLearningEngine

router = APIRouter()

@router.get("/decision-learning")
def decision_learning():
    return DecisionLearningEngine().analyze()
