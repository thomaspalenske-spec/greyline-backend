from fastapi import APIRouter

from app.services.conditional_vrp_research_engine import ConditionalVRPResearchEngine

router = APIRouter()


@router.get("/conditional-vrp-study")
def conditional_vrp_study(rerun: bool = False):
    """Conditional variance risk premium: sell 30d ATM vol only when IV is rich (causal trailing
    rank) and away from earnings. Reports gross edge, NET of cost with break-even, dual-source
    (UW + TradeStation) realized, significance, and the tail. rerun=true recomputes."""
    eng = ConditionalVRPResearchEngine()
    return eng.run() if rerun else (eng.last_study() or eng.run())
