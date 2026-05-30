from fastapi import FastAPI

from app.services.account_engine import AccountEngine
from app.services.ledger_engine import LedgerEngine
from app.services.snapshot_engine import SnapshotEngine
from app.services.position_reconciliation_engine import PositionReconciliationEngine
from app.services.schema_validator import SchemaValidator

app = FastAPI(title="GreyLine Backend")


@app.get("/")
def home():
    return {
        "system": "GreyLine",
        "status": "ONLINE"
    }


@app.get("/account")
def account():
    engine = AccountEngine()
    return engine.get_account_status()


@app.get("/ledger")
def ledger():
    engine = LedgerEngine()
    return engine.load()


@app.get("/snapshot")
def snapshot():
    engine = SnapshotEngine()
    return engine.create_snapshot()


@app.get("/reconcile")
def reconcile():
    engine = PositionReconciliationEngine()
    return engine.reconcile_positions()


@app.get("/validate-test")
def validate_test():
    validator = SchemaValidator()

    test_trade = {
        "symbol": "NVDA",
        "quantity": 1,
        "entry_price": 215.33,
        "state": "ACTIVE"
    }

    return validator.validate_trade(test_trade)
from app.services.trade_id_engine import TradeIdEngine


@app.get("/trade-id-test")
def trade_id_test():

    engine = TradeIdEngine()

    existing_trades = [
        {"symbol": "NVDA"},
        {"symbol": "MSFT"},
        {"symbol": "AVGO"}
    ]

    return {
        "trade_id": engine.generate_trade_id(existing_trades)
    }

from app.services.audit_log_engine import AuditLogEngine


@app.get("/audit-test")
def audit_test():
    engine = AuditLogEngine()

    return engine.create_log(
        action="MILESTONE_TEST",
        status="PASS",
        details={
            "milestone": "Audit Log Engine",
            "system": "GreyLine"
        }
    )


from app.services.snapshot_integrity_engine import SnapshotIntegrityEngine


@app.get("/snapshot-integrity-test")
def snapshot_integrity_test():
    engine = SnapshotIntegrityEngine()

    return engine.validate_snapshot(
        "app/snapshots/snapshot_20260530_131732.json"
    )


from app.services.restore_engine import RestoreEngine


@app.get("/restore-test")
def restore_test():
    engine = RestoreEngine()

    return engine.restore_snapshot(
        "app/snapshots/snapshot_20260530_131732.json"
    )


from app.services.snapshot_registry_engine import SnapshotRegistryEngine


@app.get("/snapshots")
def snapshots():
    engine = SnapshotRegistryEngine()

    return {
        "snapshots": engine.list_snapshots()
    }


from app.services.reconciliation_validator_engine import ReconciliationValidatorEngine


@app.get("/reconciliation-validator-test")
def reconciliation_validator_test():
    engine = ReconciliationValidatorEngine()

    ledger_positions = [
        {"symbol": "NVDA"},
        {"symbol": "MSFT"},
        {"symbol": "AVGO"}
    ]

    active_positions = [
        {"symbol": "NVDA"},
        {"symbol": "MSFT"},
        {"symbol": "AVGO"}
    ]

    return engine.validate(ledger_positions, active_positions)


from app.services.reconciliation_report_engine import ReconciliationReportEngine


@app.get("/reconciliation-report-test")
def reconciliation_report_test():
    engine = ReconciliationReportEngine()

    ledger_positions = [
        {"symbol": "NVDA"},
        {"symbol": "MSFT"},
        {"symbol": "AVGO"}
    ]

    active_positions = [
        {"symbol": "NVDA"},
        {"symbol": "MSFT"},
        {"symbol": "AVGO"}
    ]

    return engine.generate_report(
        ledger_positions,
        active_positions
    )
from app.services.account_drift_detector_engine import AccountDriftDetectorEngine


@app.get("/account-drift-test")
def account_drift_test():
    engine = AccountDriftDetectorEngine()

    return engine.detect_drift(
        ledger_equity=10000,
        reported_equity=10000
    )


from app.services.account_drift_detector_engine import AccountDriftDetectorEngine


@app.get("/account-drift-test")
def account_drift_test():
    engine = AccountDriftDetectorEngine()

    return engine.detect_drift(
        ledger_equity=10000,
        reported_equity=10000
    )
from app.services.account_health_engine import AccountHealthEngine


@app.get("/account-health-test")
def account_health_test():
    engine = AccountHealthEngine()

    return engine.evaluate_health(
        reconciliation_status="PASS",
        drift_detected=False,
        snapshot_valid=True
    )
from app.services.system_status_engine import SystemStatusEngine


@app.get("/system-status")
def system_status():
    engine = SystemStatusEngine()
    return engine.get_status()
from app.services.backend_readiness_engine import BackendReadinessEngine


@app.get("/backend-readiness")
def backend_readiness():
    engine = BackendReadinessEngine()

    return engine.evaluate_readiness(
        api_online=True,
        ledger_online=True,
        snapshot_online=True,
        reconciliation_online=True,
        account_health="HEALTHY"
    )
from app.services.milestone_registry_engine import MilestoneRegistryEngine


@app.get("/milestones")
def milestones():
    engine = MilestoneRegistryEngine()
    return engine.list_milestones()
from app.services.backend_manifest_engine import BackendManifestEngine


@app.get("/manifest")
def manifest():
    engine = BackendManifestEngine()
    return engine.get_manifest()
