from fastapi import APIRouter

from app.services.institutional.institutional_flow_provider import InstitutionalFlowProvider
from app.services.institutional.institutional_money_score_engine import InstitutionalMoneyScoreEngine

router = APIRouter()


@router.get("/institutional-flow")
def institutional_flow(symbol: str = "QQQ", option_type: str = "CALL"):
    provider = InstitutionalFlowProvider().evaluate(symbol)

    score = InstitutionalMoneyScoreEngine().evaluate({
        "symbol": symbol.upper(),
        "option_type": option_type.upper(),
        "adjusted_score": 0,
        "liquidity_score": 0,
        "signal_reliability_score": 0,
        "direction_confidence": 0,
        "setup_score": 0,
    })

    return {
        "symbol": symbol.upper(),
        "option_type": option_type.upper(),
        "institutional_flow": provider,
        "institutional_money": score,
        "status": "INSTITUTIONAL_FLOW_ENDPOINT_READY",
    }
