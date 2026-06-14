from fastapi import APIRouter

from app.services.live_trade_authority_gate_engine import LiveTradeAuthorityGateEngine

router = APIRouter()

@router.get("/live-trade-authority-gate")
def live_trade_authority_gate():
    return LiveTradeAuthorityGateEngine().evaluate()
