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
