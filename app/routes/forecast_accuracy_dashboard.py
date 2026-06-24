from fastapi import APIRouter
from app.services.forecast_accuracy_dashboard_engine import ForecastAccuracyDashboardEngine
from app.services.forecast_outcome_grader_engine import ForecastOutcomeGraderEngine

router = APIRouter()


@router.get("/forecast-accuracy-dashboard")
def forecast_accuracy_dashboard():
    grader = ForecastOutcomeGraderEngine().grade_pending()
    dashboard = ForecastAccuracyDashboardEngine().dashboard()

    return {
        "system": "GreyLine",
        "route": "ForecastAccuracyDashboardRoute",
        "grader": grader,
        "dashboard": dashboard,
        "status": "FORECAST_ACCURACY_DASHBOARD_ROUTE_READY",
    }
