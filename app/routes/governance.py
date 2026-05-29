from fastapi import APIRouter

from app.services.risk_engine import RiskEngine
from app.services.portfolio_engine import PortfolioEngine

router = APIRouter()

risk_engine = RiskEngine()
portfolio_engine = PortfolioEngine()


@router.get("/governance/status")
def governance_status():
    risk_state = risk_engine.evaluate_risk_state()
    portfolio_state = portfolio_engine.get_portfolio_state()

    return {
        "system": "GreyLine",
        "status": "ACTIVE",
        "risk_state": risk_state,
        "portfolio": portfolio_state,
        "confidence": "SIMULATED"
    }
