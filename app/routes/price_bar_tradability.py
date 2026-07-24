from fastapi import APIRouter

from app.services.price_bar_tradability_engine import PriceBarTradabilityEngine

router = APIRouter()


@router.get("/price-bar-tradability")
def price_bar_tradability(run: bool = False):
    """Where each symbol's history becomes genuinely tradable, and what's excluded because
    its signal window reaches into untraded bars. ?run=true rescans now."""
    eng = PriceBarTradabilityEngine()
    return eng.scan() if run else (eng.last_scan() or
                                   {"status": "NO_TRADABILITY_SCAN_YET",
                                    "detail": "call with ?run=true"})
