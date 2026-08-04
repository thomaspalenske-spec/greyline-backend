from fastapi import APIRouter

from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine

router = APIRouter()


@router.get("/sleeve-trade-ledger")
def sleeve_trade_ledger():
    """Direct-to-broker ETF sleeves' realized closes (trend/vol_carry/managed_futures/low_vol) — the
    trades now visible to the edge court. Read-only."""
    return SleeveTradeLedgerEngine().status()
