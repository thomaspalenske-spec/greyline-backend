from fastapi import APIRouter
from app.services.system_health_dashboard_engine import SystemHealthDashboardEngine
from app.services.system_health_snapshot_engine import SystemHealthSnapshotEngine
from app.services.unified_reliability_core_engine import UnifiedReliabilityCoreEngine

router = APIRouter()

@router.get("/system-health")
def system_health():
    return SystemHealthDashboardEngine().status()


@router.get("/system-health-snapshot")
def system_health_snapshot():
    return SystemHealthSnapshotEngine().evaluate()


@router.get("/unified-reliability-core")
def unified_reliability_core():
    return UnifiedReliabilityCoreEngine().evaluate()
