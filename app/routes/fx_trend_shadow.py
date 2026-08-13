"""FX trend shadow — the third alt-asset measurement (spot FX), zero-capital."""

from fastapi import APIRouter

from app.services.fx_trend_shadow_engine import FxTrendShadowEngine

router = APIRouter()


@router.get("/fx-trend-shadow")
def fx_trend_shadow():
    """Time-series-trend forward-test on the 6 spot-FX pairs: long positive 3-month trend / short negative,
    weekly, settled at live quotes, judged on the edge court's bar. Zero capital, no orders."""
    return FxTrendShadowEngine().report()
