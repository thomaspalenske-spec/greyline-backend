"""Dispersion / correlation-risk-premium shadow — zero-capital forward test (short index vol / long single-name vol)."""

from fastapi import APIRouter

from app.services.dispersion_shadow_engine import DispersionShadowEngine

router = APIRouter()


@router.get("/dispersion-shadow")
def dispersion_shadow():
    """Harvest implied-minus-realized correlation across a mega-cap basket vs the index, cost-net, judged on the
    edge court's bar. Zero capital, no orders. Deepens the confirmed VRP franchise into the correlation dimension."""
    return DispersionShadowEngine().report()
