from fastapi import APIRouter

from app.services.options_exit_execution_engine import OptionsExitExecutionEngine

router = APIRouter()


@router.get("/options-exit-policy")
def options_exit_policy(bid: float = 3.00, ask: float = 3.40, reason: str = "OPTIONS_TP1"):
    """Preview how an option exit would be priced. Stops/maturity => marketable limit at the bid
    (fills now, floored); take-profits => patient limit near the ask (captures spread). Replaces
    the old naked market SELLTOCLOSE, the biggest controllable cost in the options book."""
    return OptionsExitExecutionEngine().price_exit(bid, ask, reason)
