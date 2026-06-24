from fastapi import APIRouter

from app.services.forecast_reliability_dashboard_engine import ForecastReliabilityDashboardEngine

router = APIRouter()


@router.get("/forecast-reliability-dashboard")
def forecast_reliability_dashboard():
    dashboard = ForecastReliabilityDashboardEngine().dashboard()

    return {
        "system": "GreyLine",
        "route": "ForecastReliabilityDashboardRoute",
        "dashboard": dashboard,
        "status": "FORECAST_RELIABILITY_DASHBOARD_ROUTE_READY",
    }
