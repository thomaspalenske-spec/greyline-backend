from fastapi import APIRouter

from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine

router = APIRouter()


@router.get("/reality-guard")
def reality_guard():
    """Verify GreyLine is on real broker data — fantasy-land detector for the dashboard.

    verdict: REAL_DATA_VERIFIED | REAL_DATA_WITH_WARNINGS | FANTASY_DETECTED.
    """
    return GreyLineRealityGuardEngine().check()
