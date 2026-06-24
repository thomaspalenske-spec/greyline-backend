from fastapi import APIRouter
from app.services.forecast_accuracy_dashboard_engine import ForecastAccuracyDashboardEngine
from app.services.forecast_outcome_grader_engine import ForecastOutcomeGraderEngine
from app.services.forecast_feedback_engine import ForecastFeedbackEngine
from app.services.forecast_weight_advisor_engine import ForecastWeightAdvisorEngine

router = APIRouter()


@router.get("/forecast-accuracy-dashboard")
def forecast_accuracy_dashboard():
    grader = ForecastOutcomeGraderEngine().grade_pending()
    dashboard = ForecastAccuracyDashboardEngine().dashboard()
    feedback = ForecastFeedbackEngine().evaluate()
    weight_advisor = ForecastWeightAdvisorEngine().advise()

    return {
        "system": "GreyLine",
        "route": "ForecastAccuracyDashboardRoute",
        "grader": grader,
        "dashboard": dashboard,
        "feedback": feedback,
        "weight_advisor": weight_advisor,
        "status": "FORECAST_ACCURACY_DASHBOARD_ROUTE_READY",
    }
