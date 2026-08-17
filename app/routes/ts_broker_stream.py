"""Observability for the TradeStation brokerage positions stream cache-warmer — engine decides, renders only."""

from fastapi import APIRouter

from app.services.tradestation_broker_stream_engine import TradeStationBrokerStreamEngine

router = APIRouter()


@router.get("/ts-broker-stream")
def ts_broker_stream_status():
    """Live state of the positions stream cache-warmer: enabled/alive/connected, mirror size, whether it's
    SYNCED (its book agrees with a cache-bypassing REST cross-check), the last cross-check delta, frames,
    warm-writes, staleness. It only warms the positions cache WHILE synced — any mismatch/gap desyncs it to
    the REST read, so this is a health + agreement view, not a dependency. `synced` + a clean `last_crosscheck`
    over time is the verdict for whether the stream is trustworthy enough to lean on."""
    return TradeStationBrokerStreamEngine.status()
