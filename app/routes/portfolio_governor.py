from typing import Optional

from fastapi import APIRouter, Query

from app.services.portfolio_governor_engine import PortfolioGovernorEngine

router = APIRouter()


@router.get("/portfolio-governor")
def portfolio_governor(
    deployment_score: float = Query(0),
    candidate_symbol: Optional[str] = Query(None),
):
    return PortfolioGovernorEngine().evaluate(
        deployment_score=deployment_score,
        candidate_symbol=candidate_symbol,
    )
