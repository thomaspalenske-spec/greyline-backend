from fastapi import APIRouter

from app.services.opportunity_summary_engine import OpportunitySummaryEngine
from app.services.opportunity_symmetry_engine import OpportunitySymmetryEngine
from app.services.bear_market_opportunity_engine import BearMarketOpportunityEngine
from app.services.institutional_flow_engine import InstitutionalFlowEngine

router = APIRouter()


@router.get("/opportunity-balance")
def opportunity_balance():
    opportunity_summary = OpportunitySummaryEngine().get_summary(limit=50)
    opportunities = opportunity_summary.get("opportunities", [])

    symmetry = OpportunitySymmetryEngine().evaluate(opportunities)
    bear = BearMarketOpportunityEngine().evaluate(opportunities)
    flow = InstitutionalFlowEngine().evaluate({
        "symbols_scored": opportunity_summary.get("symbols_scored", 0),
        "top_candidate": opportunities[0] if opportunities else None,
        "symmetry": symmetry,
    })

    return {
        "system": "GreyLine",
        "endpoint": "/opportunity-balance",
        "purpose": "Verify call and put opportunity symmetry and institutional flow inference.",
        "symbols_scored": opportunity_summary.get("symbols_scored", 0),
        "opportunity_count": len(opportunities),
        "symmetry": symmetry,
        "bear_market_opportunity": bear,
        "institutional_flow": flow,
        "status": "OPPORTUNITY_BALANCE_READY",
    }
