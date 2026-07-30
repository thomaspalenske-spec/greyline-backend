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


@router.get("/scheduled-reports")
def scheduled_reports():
    """Preview the auto pre-open pager + post-close report (what they'd say now; does not send)."""
    from app.services.scheduled_operator_reports_engine import ScheduledOperatorReportsEngine
    return ScheduledOperatorReportsEngine.preview()
