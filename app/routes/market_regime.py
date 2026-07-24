from fastapi import APIRouter

from app.services.market_regime_gate_engine import MarketRegimeGateEngine

router = APIRouter()


@router.get("/market-regime")
def market_regime():
    """Current broad-market regime (index vs 200DMA) and whether the dip-buy gate is active.
    RISK_OFF blocks new bullish dip-buys; bearish setups still trade."""
    e = MarketRegimeGateEngine()
    a = e.assess()
    a["gate_enabled"] = e.enabled()
    return a
