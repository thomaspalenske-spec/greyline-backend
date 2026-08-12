"""Observability for the TradeStation quote stream cache-warmer — engine decides, this only renders."""

from fastapi import APIRouter

from app.services.tradestation_quote_stream_engine import TradeStationQuoteStreamEngine

router = APIRouter()


@router.get("/ts-quote-stream")
def ts_quote_stream_status():
    """Live state of the long-lived quote stream: enabled/alive/connected, symbols, frames ingested,
    seconds since the last frame, reconnects, last error. The stream only WARMS the quote cache — when it's
    stale or down, callers fall back to REST, so this is a health view, not a dependency."""
    return TradeStationQuoteStreamEngine.status()
