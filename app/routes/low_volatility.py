from fastapi import APIRouter
from app.services.low_volatility_engine import LowVolatilityEngine

router = APIRouter()


@router.get("/low-volatility")
def low_volatility():
    """Low-volatility / betting-against-beta factor sleeve (the earnings-vol replacement candidate):
    inverse-vol-weighted basket of liquid low-vol ETFs, whole-share. Gated OFF by GREYLINE_LOW_VOL_ENABLED;
    forward-tested under the pre-registered edge-proof protocol."""
    return LowVolatilityEngine().status()


@router.get("/low-volatility-shadow")
def low_volatility_shadow():
    """Zero-capital forward-test of the low-vol basket: hypothetical daily P&L on settled bars (NO orders,
    NO budget) using the sleeve's own inverse-vol weights, with the thesis check = smaller drawdown than
    SPY. Verdict mirrors the edge court (accumulating -> measuring)."""
    from app.services.low_volatility_shadow_engine import LowVolatilityShadowEngine
    return LowVolatilityShadowEngine().report()
