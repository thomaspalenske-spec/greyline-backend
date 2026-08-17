from fastapi import APIRouter

from app.services.mechanical_flow_research_engine import MechanicalFlowResearchEngine

router = APIRouter()


@router.get("/mechanical-flow-research")
def mechanical_flow_research(run: bool = False):
    """Pre-registered study of whether calendar-driven (forced) flow leaves a tradable
    effect. RESEARCH ONLY — reads history, never trades. ?run=true recomputes."""
    eng = MechanicalFlowResearchEngine()
    return eng.run() if run else (eng.last_study() or
                                  {"status": "NO_STUDY_RUN_YET", "detail": "call with ?run=true"})
