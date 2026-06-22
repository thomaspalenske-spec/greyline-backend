from fastapi import APIRouter
from app.services.options_paper_trade_ledger_engine import OptionsPaperTradeLedgerEngine
from app.services.options_trade_forensics_engine import OptionsTradeForensicsEngine

router = APIRouter()


@router.get("/options-trade-forensics")
def options_trade_forensics():
    history = OptionsPaperTradeLedgerEngine().history(limit=1000)
    trades = history.get("trades", [])

    closed_trades = [t for t in trades if t.get("status") == "CLOSED"]
    analyses = [OptionsTradeForensicsEngine().analyze(t) for t in closed_trades]

    return {
        "system": "GreyLine",
        "engine": "OptionsTradeForensicsRoute",
        "closed_trade_count": len(closed_trades),
        "forensics": analyses,
        "status": "OPTIONS_TRADE_FORENSICS_REPORT_READY",
    }
