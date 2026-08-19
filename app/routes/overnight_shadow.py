from fastapi import APIRouter

from app.services.overnight_anomaly_shadow_engine import OvernightAnomalyShadowEngine

router = APIRouter()


@router.get("/overnight-shadow")
def overnight_shadow():
    """Zero-capital forward-test of the OVERNIGHT-return anomaly (close->open premium, held overnight / flat
    intraday) on the tightest broad-index ETFs. forward_shadow = the rigorous court verdict (accrues ~1
    obs/day). historical_context = in-sample insight (real gross ~+9.8%/yr Sharpe ~0.8, but cost-fragile:
    breakeven ~3.7bps round-trip; see cost_sweep). Orthogonal to the VRP vol premium; traded as cheap equity."""
    return OvernightAnomalyShadowEngine().report()
