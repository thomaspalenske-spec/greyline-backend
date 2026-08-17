"""The extended ETF universe — the 52 scanned ETFs added as tracked candidates. Engine decides, this renders."""

from fastapi import APIRouter

from app.services.extended_etf_universe_engine import ExtendedEtfUniverseEngine

router = APIRouter()


@router.get("/extended-etf-universe")
def extended_etf_universe(sleeve: str = None):
    """The 52 ETFs added to GreyLine's universe as TRACKED candidates (not armed). Pass ?sleeve=trend to see
    which candidates fit a given sleeve. Each still clears the edge court before it trades."""
    if sleeve:
        return {"sleeve": sleeve, "candidates": ExtendedEtfUniverseEngine.for_sleeve(sleeve),
                "status": "EXTENDED_ETF_UNIVERSE_FOR_SLEEVE"}
    return ExtendedEtfUniverseEngine.snapshot()
