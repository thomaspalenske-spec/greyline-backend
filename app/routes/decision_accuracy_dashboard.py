from fastapi import APIRouter
from app.services.decision_accuracy_dashboard_engine import DecisionAccuracyDashboardEngine

router = APIRouter()

@router.get("/decision-accuracy-dashboard")
def decision_accuracy_dashboard():
    return DecisionAccuracyDashboardEngine().summarize()
