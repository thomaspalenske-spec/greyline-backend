from fastapi import APIRouter
from app.services.decision_metrics_dashboard_engine import (
    DecisionMetricsDashboardEngine,
)

router = APIRouter()

@router.get("/decision-metrics")
def decision_metrics():
    return DecisionMetricsDashboardEngine().summarize()
