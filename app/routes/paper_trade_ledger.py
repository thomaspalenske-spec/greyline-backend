from fastapi import APIRouter
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine

router = APIRouter()

@router.post("/paper-trade-ledger/open")
def open_trade(symbol: str = "PLTR", side: str = "BUY", quantity: int = 1, entry_price: float = 0.0):
    return PaperTradeLedgerEngine().open_trade(symbol, side, quantity, entry_price)

@router.post("/paper-trade-ledger/close")
def close_trade(symbol: str = "PLTR", exit_price: float = 0.0):
    return PaperTradeLedgerEngine().close_latest(symbol, exit_price)

@router.get("/paper-trade-ledger")
def history():
    return PaperTradeLedgerEngine().history()
