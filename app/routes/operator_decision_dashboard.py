from fastapi import APIRouter
from app.services.operator_decision_dashboard_engine import OperatorDecisionDashboardEngine

router = APIRouter()

@router.get("/operator-decision-dashboard")
def operator_decision_dashboard():
    return OperatorDecisionDashboardEngine().summarize()
