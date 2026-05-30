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
