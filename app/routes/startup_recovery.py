from fastapi import APIRouter
from app.services.startup_recovery_engine import StartupRecoveryEngine

router = APIRouter()

@router.get("/startup-readiness")
def startup_readiness():
    return StartupRecoveryEngine().readiness()
