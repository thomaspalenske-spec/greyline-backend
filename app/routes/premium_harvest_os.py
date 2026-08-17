from fastapi import APIRouter

from app.services.premium_harvest_os_engine import PremiumHarvestOSEngine
from app.services.catalyst_risk_overlay_engine import CatalystRiskOverlayEngine

router = APIRouter()


@router.get("/premium-harvest-os")
def premium_harvest_os():
    """The unified face of the Variance Risk Premium Harvesting OS: premium catalog, harvest
    universe, structure, risk budget, catalyst defense, and the out-of-sample scoreboard."""
    return PremiumHarvestOSEngine().status()


@router.get("/catalyst-overlay")
def catalyst_overlay():
    """Scheduled vol events (Fed/CPI/PCE/jobs/FDA) and whether the OS is deferring new premium to
    avoid selling straight into a known tail."""
    return CatalystRiskOverlayEngine().status()
