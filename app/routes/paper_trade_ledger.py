from fastapi import APIRouter
from pydantic import BaseModel

from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine


router = APIRouter()


class PaperTradeRequest(BaseModel):
    symbol: str
    side: str
    quantity: int
    entry_price: float


@router.get("/paper-trade-ledger/history")
def paper_trade_history():
    return PaperTradeLedgerEngine().history()


@router.post("/paper-trade-ledger/record")
def paper_trade_record(request: PaperTradeRequest):
    return PaperTradeLedgerEngine().record_trade(
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        entry_price=request.entry_price,
    )
