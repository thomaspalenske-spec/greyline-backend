from fastapi import APIRouter

from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
from app.services.disaster_recovery_engine import DisasterRecoveryEngine

router = APIRouter()


@router.get("/broker-protection")
def broker_protection(ensure: bool = False, dry_run: bool = True):
    """Resting disaster stops at the broker — the only protection that survives GreyLine being
    down. ?ensure=true&dry_run=false arms them (requires GREYLINE_BROKER_PROTECTIVE_STOPS=true)."""
    eng = BrokerProtectiveStopEngine()
    return eng.ensure_stops(dry_run=dry_run) if ensure else eng.status()


@router.get("/disaster-recovery")
def disaster_recovery(backup: bool = False, tier2: bool = False):
    """Off-machine backup of the UNRECOVERABLE data (options surface, PIT archive, panels,
    ledgers) — forward-only data no API can rebuild. ?backup=true runs one now."""
    eng = DisasterRecoveryEngine()
    return eng.backup(tier2=tier2) if backup else eng.status()
