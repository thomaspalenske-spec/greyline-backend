from fastapi import APIRouter

from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine


router = APIRouter()


@router.post("/paper-trade-executor/run")
def run_paper_trade_executor():
    decision = GreyLineMasterDecisionEngine().evaluate()

    top_candidate = decision.get("top_candidate", {})
    decision_value = decision.get("decision")

    if decision_value not in ["EXECUTE_SIGNAL_BLOCKED_READ_ONLY", "EXECUTE"]:
        return {
            "system": "GreyLine",
            "source": "PAPER_TRADE_EXECUTOR",
            "paper_trade_recorded": False,
            "reason": "NO_EXECUTE_SIGNAL",
            "decision": decision_value,
            "status": "PAPER_TRADE_EXECUTOR_NO_ACTION",
        }

    symbol = top_candidate.get("symbol")

    if not symbol:
        return {
            "system": "GreyLine",
            "source": "PAPER_TRADE_EXECUTOR",
            "paper_trade_recorded": False,
            "reason": "NO_SYMBOL_FOUND",
            "status": "PAPER_TRADE_EXECUTOR_BLOCKED",
        }

    trade = PaperTradeLedgerEngine().record_trade(
        symbol=symbol,
        side="BUY",
        quantity=1,
        entry_price=0.0,
        source="PAPER_TRADE_EXECUTOR_FROM_MASTER_DECISION",
    )

    return {
        "system": "GreyLine",
        "source": "PAPER_TRADE_EXECUTOR",
        "paper_trade_recorded": True,
        "decision": decision_value,
        "symbol": symbol,
        "trade": trade,
        "status": "PAPER_TRADE_EXECUTOR_RECORDED",
    }
