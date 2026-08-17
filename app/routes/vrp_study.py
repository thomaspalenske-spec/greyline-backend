from fastapi import APIRouter

from app.services.vrp_research_engine import VRPResearchEngine

router = APIRouter()


@router.get("/vrp-study")
def vrp_study(rerun: bool = False):
    """Variance risk premium study: implied vs forward-realized vol (UW), realized cross-checked
    against TradeStation prices. Reports significance, magnitude vs option cost, tail, and the
    dual-source agreement. rerun=true recomputes; otherwise returns the last saved study."""
    eng = VRPResearchEngine()
    return eng.run() if rerun else (eng.last_study() or eng.run())
