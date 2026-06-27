from fastapi import APIRouter
from app.services.system_health_dashboard_engine import SystemHealthDashboardEngine
from app.services.system_health_snapshot_engine import SystemHealthSnapshotEngine

router = APIRouter()

@router.get("/system-health")
def system_health():
    return SystemHealthDashboardEngine().status()


@router.get("/system-health-snapshot")
def system_health_snapshot():
    return SystemHealthSnapshotEngine().evaluate()
