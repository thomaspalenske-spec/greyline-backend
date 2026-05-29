from fastapi import FastAPI
from app.routes.governance import router as governance_router
from app.services.account_engine import AccountEngine
from app.services.ledger_engine import LedgerEngine

app = FastAPI(title="GreyLine Backend")

app.include_router(governance_router)

@app.get("/")
def root():
    return {
        "system": "GreyLine",
        "status": "ONLINE"
    }

@app.get("/account")
def account():
    return AccountEngine().get_account_status()
@app.get("/ledger")
def ledger():
    return LedgerEngine().load()