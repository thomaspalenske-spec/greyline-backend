"""Earnings-vol harvest status — the forward-testing defined-risk sleeve (armed state, candidates)."""

from fastapi import APIRouter

from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine

router = APIRouter()


@router.get("/earnings-vol")
def earnings_vol():
    """Armed state, open earnings-vol condors, deployed risk, and tonight's rich-IV earnings candidates."""
    return EarningsVolHarvestEngine().status()


@router.get("/earnings-vol/fire-readiness")
def earnings_vol_fire_readiness():
    """READ-ONLY: will the earnings sleeve open condors at the next in-session cycle? Every gate between
    armed and a booked condor, with the reason if not. Dry-run — places nothing."""
    return EarningsVolHarvestEngine().fire_readiness()


@router.get("/earnings-vol/dress-rehearsal")
def earnings_vol_dress_rehearsal():
    """READ-ONLY pre-fire trace: builds the earnings condors against LIVE UW chains (off-hours capable),
    validates each is a sound defined-risk structure, and projects the round-trip into the edge court.
    Proves the first real fires will build, fill, reconcile, and be COUNTED. Places nothing."""
    return EarningsVolHarvestEngine().dress_rehearsal()
