"""Futures TSMOM shadow — the real managed-futures test (vs ETF proxies), measured zero-capital."""

from fastapi import APIRouter

from app.services.futures_tsmom_shadow_engine import FuturesTsmomShadowEngine

router = APIRouter()


@router.get("/futures-tsmom-shadow")
def futures_tsmom_shadow():
    """Time-series-momentum forward-test on the 19 continuous futures: long positive-trend / short negative,
    equal-weight, monthly, settled at live quotes, judged on the edge court's bar. Zero capital, no orders."""
    return FuturesTsmomShadowEngine().report()
