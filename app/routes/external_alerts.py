from fastapi import APIRouter

from app.services.external_alert_engine import ExternalAlertEngine

router = APIRouter()


@router.get("/external-alerts")
def external_alerts():
    """Whether a CRITICAL event can leave this machine. No external channel = failures are
    invisible when the operator is away (the silent-backfill case)."""
    return ExternalAlertEngine().status()


@router.post("/external-alerts/test")
def external_alerts_test(dry_run: bool = True):
    """Fire a test alert. dry_run=true (default) reports which channels WOULD fire without
    sending; dry_run=false actually dispatches through every configured channel."""
    return ExternalAlertEngine().dispatch(
        title="GreyLine alert test",
        message="This is a test of the external alert path.",
        severity="INFO", fingerprint="ALERT_TEST", force=True, dry_run=dry_run)
