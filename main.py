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
