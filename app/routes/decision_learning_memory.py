from fastapi import APIRouter
from app.services.decision_learning_memory_engine import DecisionLearningMemoryEngine

router = APIRouter()

@router.post("/decision-learning-record")
def decision_learning_record():
    return DecisionLearningMemoryEngine().record_current_learning()

@router.get("/decision-learning-history")
def decision_learning_history():
    return DecisionLearningMemoryEngine().get_history()
