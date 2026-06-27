from fastapi import APIRouter
from app.services.system_health_dashboard_engine import SystemHealthDashboardEngine
from app.services.system_health_snapshot_engine import SystemHealthSnapshotEngine
from app.services.unified_reliability_core_engine import UnifiedReliabilityCoreEngine
from app.services.reliability_governor_engine import ReliabilityGovernorEngine

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


@router.get("/reliability-brief")
def reliability_brief():
    r = UnifiedReliabilityCoreEngine().evaluate()
    return {
        "timestamp": r.get("timestamp"),
        "system": "GreyLine",
        "overall_reliability": r.get("overall_reliability"),
        "summary": r.get("summary"),
        "reliability_score": r.get("reliability_score"),
        "max_score": r.get("max_score"),
        "checks": r.get("checks"),
        "status": "RELIABILITY_BRIEF_READY",
    }


@router.get("/reliability-governor")
def reliability_governor():
    return ReliabilityGovernorEngine().evaluate()
