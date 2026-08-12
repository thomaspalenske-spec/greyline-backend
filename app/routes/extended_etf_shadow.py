"""Extended-ETF shadow forward-test — the zero-capital measurement layer for the 52-ETF universe."""

from fastapi import APIRouter

from app.services.extended_etf_shadow_engine import ExtendedEtfShadowEngine

router = APIRouter()


@router.get("/extended-etf-shadow")
def extended_etf_shadow():
    """Cross-sectional-momentum forward-test on the new ETF universe: rank by trailing return, hold top-K a
    week, settle at live quotes, judged on the live edge court's bar. Zero capital, no orders."""
    return ExtendedEtfShadowEngine().report()
