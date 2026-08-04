from fastapi import APIRouter
from app.services.low_volatility_engine import LowVolatilityEngine

router = APIRouter()


@router.get("/low-volatility")
def low_volatility():
    """Low-volatility / betting-against-beta factor sleeve (the earnings-vol replacement candidate):
    inverse-vol-weighted basket of liquid low-vol ETFs, whole-share. Gated OFF by GREYLINE_LOW_VOL_ENABLED;
    forward-tested under the pre-registered edge-proof protocol."""
    return LowVolatilityEngine().status()
