from fastapi import APIRouter
from app.services.decision_performance_attribution_engine import (
    DecisionPerformanceAttributionEngine,
)

router = APIRouter()

@router.get("/decision-performance")
def decision_performance():
    return DecisionPerformanceAttributionEngine().analyze()
