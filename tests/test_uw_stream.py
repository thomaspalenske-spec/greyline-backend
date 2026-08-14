"""UW WebSocket cache-warmer: frame ingest → warm cache, join-acks skipped, staleness, gating. Hermetic —
no socket (the _ingest/latest/config logic is exercised directly)."""

import time

import pytest

from app.services.uw_stream_engine import UWStreamEngine as U


@pytest.fixture(autouse=True)
def _reset():
    U._cache = {}
    U._state = dict(U._state, frames=0, last_frame_at=None, last_error=None)
    yield
    U._cache = {}


def test_data_frame_warms_cache():
    U._ingest('["price:SPY", {"price": 772.5, "t": 1}]')
    assert U.latest("price:SPY") == {"price": 772.5, "t": 1}
    assert U._state["frames"] == 1


def test_join_ack_is_not_cached():
    U._ingest('["price:SPY", {"response": {}, "status": "ok"}]')
    assert U.latest("price:SPY") is None                 # the join ack is not data
    assert U._state["frames"] == 0


def test_error_frame_recorded_not_cached():
    U._ingest('{"error": "Invalid payload, ignoring message"}')
    assert not U._cache
    assert "Invalid payload" in (U._state["last_error"] or "")


def test_stale_value_falls_back_to_none():
    U._ingest('["gex:SPY", {"net_gamma": -1.2e9}]')
    assert U.latest("gex:SPY", max_age_s=60) is not None
    U._cache["gex:SPY"]["ts"] = time.time() - 120        # age it past the window
    assert U.latest("gex:SPY", max_age_s=60) is None     # never trust an aged push; caller uses REST


def test_channels_from_env(monkeypatch):
    monkeypatch.setenv("GREYLINE_UW_STREAM_CHANNELS", "price:TSLA gex:QQQ")
    chans = U._channels()
    assert "price:TSLA" in chans and "gex:QQQ" in chans and "price:SPY" in chans   # defaults + env


def test_disabled_start_is_noop(monkeypatch):
    monkeypatch.delenv("GREYLINE_UW_STREAM_ENABLED", raising=False)
    assert U.enabled() is False
    assert U.start_if_enabled()["status"] == "UW_STREAM_DISABLED"
    assert not (U._thread and U._thread.is_alive())
