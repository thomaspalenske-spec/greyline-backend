from fastapi import APIRouter

from app.services.price_bar_cross_source_engine import PriceBarCrossSourceEngine

router = APIRouter()


@router.get("/price-bar-cross-source")
def price_bar_cross_source(run: bool = False, sample: int = None, symbols: str = None):
    """Last cross-source reconciliation of the price bars against TradeStation barcharts.

    ?run=true forces a fresh comparison now (read-only against the broker — it fetches
    barcharts, never places an order). ?symbols=AAPL,MSFT checks specific names.
    """
    eng = PriceBarCrossSourceEngine()
    if run or symbols:
        syms = [s.strip().upper() for s in symbols.split(",")] if symbols else None
        return eng.reconcile(symbols=syms, sample=sample)
    return eng.last_run() or {"status": "NO_CROSS_SOURCE_RUN_YET",
                              "detail": "call with ?run=true to reconcile now"}
