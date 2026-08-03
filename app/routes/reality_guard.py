from fastapi import APIRouter

from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine

router = APIRouter()


@router.get("/reality-guard")
def reality_guard():
    """Verify GreyLine is on real broker data — fantasy-land detector for the dashboard.

    verdict: REAL_DATA_VERIFIED | REAL_DATA_WITH_WARNINGS | BROKER_READ_DEGRADED | FANTASY_DETECTED.
    BROKER_READ_DEGRADED (amber) is an UNVERIFIABLE live read (honest last-known-good/unknown), NOT
    fabrication — it is deliberately kept out of the red FANTASY_DETECTED alarm so the guard never cries
    wolf on a benign, self-healing degraded read. FANTASY_DETECTED is reserved for fake-data-as-real.
    """
    return GreyLineRealityGuardEngine().check()
