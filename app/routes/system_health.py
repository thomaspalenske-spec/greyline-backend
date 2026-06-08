from fastapi import APIRouter
from app.services.system_health_dashboard_engine import SystemHealthDashboardEngine

router = APIRouter()

@router.get("/system-health")
def system_health():
    return SystemHealthDashboardEngine().status()
