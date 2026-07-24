from fastapi import APIRouter

from app.services.options_reality_capture_engine import OptionsRealityCaptureEngine

router = APIRouter()


@router.get("/options-reality")
def options_reality(capture: bool = False):
    """The accumulating options surface panel — the ONLY evidence base an options edge can be
    verified against (options cannot be backtested: no historical contract data exists).
    ?capture=true records today's surface now."""
    eng = OptionsRealityCaptureEngine()
    return eng.capture_if_due() if capture else eng.coverage()
