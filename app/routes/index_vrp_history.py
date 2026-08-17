from fastapi import APIRouter

from app.services.index_vrp_history_research_engine import IndexVRPHistoryResearchEngine

router = APIRouter()


@router.get("/index-vrp-history")
def index_vrp_history(rerun: bool = False):
    """The index variance-risk-premium over the LONG history (VIX vs forward realized SPY vol, 2003-2026)
    — the crash-regime + power test the 1-year UW study cannot run. Reports VRP by year (crashes visible),
    the unconditional edge, and the rich-IV tercile/decile conditioning (which, unlike the 1-year single-name
    result, does NOT lift the index edge). Same inference discipline as /conditional-vrp-study. rerun=true
    recomputes (fast — reads on-disk VIX + SPY)."""
    eng = IndexVRPHistoryResearchEngine()
    return eng.run() if rerun else (eng.last_study() if eng.last_study().get("status") != "NO_STUDY_YET" else eng.run())
