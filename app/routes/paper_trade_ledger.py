from fastapi import APIRouter, Body
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine

router = APIRouter()


@router.post("/paper-trade-ledger/open")
def open_trade(payload: dict = Body(default={})):
    symbol = payload.get("symbol", "PLTR")
    side = payload.get("side", "BUY")
    quantity = int(payload.get("quantity", 1))
    entry_price = float(payload.get("entry_price", 0.0))

    return PaperTradeLedgerEngine().open_trade(
        symbol=symbol,
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        directional_bias=payload.get("directional_bias"),
        option_type=payload.get("option_type"),
        trade_intent=payload.get("trade_intent"),
        bullish_score=payload.get("bullish_score"),
        bearish_score=payload.get("bearish_score"),
        opposing_score=payload.get("opposing_score"),
        direction_confidence=payload.get("direction_confidence"),
    )


@router.post("/paper-trade-ledger/close")
def close_trade(payload: dict = Body(default={})):
    symbol = payload.get("symbol", "PLTR")
    exit_price = float(payload.get("exit_price", 0.0))

    return PaperTradeLedgerEngine().close_latest(symbol=symbol, exit_price=exit_price)


@router.get("/paper-trade-ledger")
def history():
    return PaperTradeLedgerEngine().history()
