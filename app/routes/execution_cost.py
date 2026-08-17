from fastapi import APIRouter

from app.services.options_execution_cost_engine import OptionsExecutionCostEngine
from app.services.options_fee_model_engine import OptionsFeeModelEngine
from app.services.session_liquidity_window_engine import SessionLiquidityWindowEngine

router = APIRouter()


@router.get("/execution-cost")
def execution_cost(bid: float = 3.20, ask: float = 4.25, mid: float = 0.0, contracts: int = 1):
    """Round-trip execution cost of a contract (spread + fees, bps of premium) and whether it
    clears the tradeability gate. This is the number contract selection now ranks on."""
    c = OptionsExecutionCostEngine()
    ok, est = c.viable(bid, ask, mid or None, contracts)
    return {**est, "viable": ok, "max_roundtrip_bps": c.max_roundtrip_bps(),
            "fee_per_contract": OptionsFeeModelEngine().fee_per_contract()}


@router.get("/liquidity-window")
def liquidity_window():
    """Whether we are in the liquid mid-session. New option entries wait for this window to avoid
    the wide open/close spread; exits are never gated by it."""
    return SessionLiquidityWindowEngine().status()
