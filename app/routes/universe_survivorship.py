from fastapi import APIRouter

from app.services.universe_survivorship_engine import UniverseSurvivorshipEngine

router = APIRouter()


@router.get("/universe-survivorship")
def universe_survivorship(snapshot: bool = False):
    """Point-in-time universe coverage and retained delisted names.
    ?snapshot=true records today's membership now."""
    eng = UniverseSurvivorshipEngine()
    if snapshot:
        out = eng.snapshot()
        out["departures"] = eng.detect_departures()
        return out
    return eng.status()
