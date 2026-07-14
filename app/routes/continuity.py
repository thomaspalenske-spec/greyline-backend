from fastapi import APIRouter

from app.services.continuity_monitor_engine import ContinuityMonitorEngine

router = APIRouter()


@router.get("/continuity")
def continuity():
    """Did accumulation actually stay continuous? Finds gaps (sleep/reboot/crash) + live status."""
    return ContinuityMonitorEngine().diagnose()
