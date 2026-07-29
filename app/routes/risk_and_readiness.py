"""Book-level risk governor + pre-open readiness audit — read-only operator views."""

from fastapi import APIRouter

from app.services.mission_risk_governor_engine import MissionRiskGovernorEngine
from app.services.pre_open_readiness_engine import PreOpenReadinessEngine

router = APIRouter()


@router.get("/mission-risk-governor")
def mission_risk_governor():
    """Book-level daily P&L and deployment vs the mission book, with the warn/halt thresholds."""
    return MissionRiskGovernorEngine().snapshot()


@router.get("/pre-open-readiness")
def pre_open_readiness():
    """Audit every link in the open chain — reset, capital, data feeds, armed paths, guard, accounting."""
    return PreOpenReadinessEngine().audit()
