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


@router.get("/git-data-backup")
def git_data_backup_status():
    """Status of the off-machine git backup of the unrecoverable data (the service-compatible channel)."""
    from app.services.git_data_backup_engine import GitDataBackupEngine
    return GitDataBackupEngine().status()


@router.post("/git-data-backup/run")
def git_data_backup_run():
    """Run the git backup NOW in the service process — the test of whether the background service
    can actually push (keychain access), and the manual trigger."""
    from app.services.git_data_backup_engine import GitDataBackupEngine
    return GitDataBackupEngine().backup()


@router.get("/disaster-restore-drill")
def disaster_restore_drill_status():
    """Last restore-drill result — whether the off-machine backup is proven RESTORABLE. Read-only."""
    from app.services.disaster_restore_drill_engine import DisasterRestoreDrillEngine
    return DisasterRestoreDrillEngine().status()


@router.post("/disaster-restore-drill/run")
def disaster_restore_drill_run():
    """Run the restore drill NOW — fetch the real remote backup branch and verify every TIER1 file is
    present, non-empty, and parses. Read-only (never touches live data); does not page."""
    from app.services.disaster_restore_drill_engine import DisasterRestoreDrillEngine
    return DisasterRestoreDrillEngine().drill()
