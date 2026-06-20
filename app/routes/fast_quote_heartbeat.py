from fastapi import APIRouter, Query

from app.services.fast_quote_heartbeat_service import FastQuoteHeartbeatService

router = APIRouter()


@router.post("/fast-quote-heartbeat/start")
def start_fast_quote_heartbeat(
    symbols: str = Query("AMD,NVDA"),
    interval_market_open_seconds: int = Query(5),
    interval_market_closed_seconds: int = Query(300),
):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    return FastQuoteHeartbeatService.start(
        symbols=symbol_list,
        interval_market_open_seconds=interval_market_open_seconds,
        interval_market_closed_seconds=interval_market_closed_seconds,
    )


@router.post("/fast-quote-heartbeat/stop")
def stop_fast_quote_heartbeat():
    return FastQuoteHeartbeatService.stop()


@router.post("/fast-quote-heartbeat/run-once")
def run_once_fast_quote_heartbeat(symbols: str = Query("AMD,NVDA")):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    return FastQuoteHeartbeatService.run_once(symbols=symbol_list)


@router.get("/fast-quote-heartbeat/status")
def fast_quote_heartbeat_status():
    return FastQuoteHeartbeatService.status()
