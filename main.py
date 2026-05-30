from fastapi import FastAPI

from app.services.account_engine import AccountEngine
from app.services.ledger_engine import LedgerEngine
from app.services.snapshot_engine import SnapshotEngine
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

    data = {
        "account": "GreyLine Account 3",
        "timestamp": "manual_test"
    }

    return engine.create_snapshot(data)
@app.get("/test-trade")
def test_trade():

    engine = LedgerEngine()

    return engine.add_trade(
        {
            "symbol": "NVDA",
            "quantity": 1,
            "entry_price": 215.33,
            "state": "ACTIVE"
        }
    )