from fastapi import APIRouter

from app.services.pre_trade_risk_gate_engine import PreTradeRiskGateEngine

router = APIRouter()

@router.get("/pre-trade-risk-gate")
def pre_trade_risk_gate(
    symbol: str = "NVDA",
    side: str = "BUY",
    quantity: int = 1,
    estimated_order_value: float = 0.0,
):
    return PreTradeRiskGateEngine().evaluate(
        symbol=symbol,
        side=side,
        quantity=quantity,
        estimated_order_value=estimated_order_value,
    )
