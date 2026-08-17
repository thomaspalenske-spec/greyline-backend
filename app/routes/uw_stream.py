"""Observability for the UW WebSocket cache-warmer — engine decides, renders only."""

from fastapi import APIRouter

from app.services.uw_stream_engine import UWStreamEngine

router = APIRouter()


@router.get("/uw-stream")
def uw_stream_status():
    """Live state of the UW WebSocket push feed: enabled/alive/connected, joined channels, cached
    channels, frames, seconds since last frame, reconnects. It only WARMS a UW cache — callers keep
    their REST path when it's stale/off, so this is a health view, not a dependency."""
    return UWStreamEngine.status()
