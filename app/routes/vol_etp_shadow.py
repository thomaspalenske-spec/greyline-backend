"""Long-vol ETP shadow — the regime-conditioned long-vol leg, measured zero-capital."""

from fastapi import APIRouter

from app.services.vol_etp_shadow_engine import VolEtpShadowEngine

router = APIRouter()


@router.get("/vol-etp-shadow")
def vol_etp_shadow():
    """Forward-test of long VXX ONLY in backwardation (VIX>=VIX3M) — the long-vol leg that complements the
    SVXY short-vol carry sleeve. Weekly cohorts, live settlement, judged on the edge court's bar. Zero capital."""
    return VolEtpShadowEngine().report()
