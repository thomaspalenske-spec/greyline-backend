"""Earnings-vol harvest status — the forward-testing defined-risk sleeve (armed state, candidates)."""

from fastapi import APIRouter

from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine

router = APIRouter()


@router.get("/earnings-vol")
def earnings_vol():
    """Armed state, open earnings-vol condors, deployed risk, and tonight's rich-IV earnings candidates."""
    return EarningsVolHarvestEngine().status()
