from fastapi import APIRouter

from app.services.transaction_ledger_engine import TransactionLedgerEngine

router = APIRouter()


@router.get("/transactions-rolling")
def transactions_rolling():
    """Rolling 2-day transaction ledger: yesterday's completed session + today's running tally, from
    GreyLine's own sleeve ledgers. Rolls automatically at the open (pure function of ET date + timestamps)."""
    return TransactionLedgerEngine().rolling()
