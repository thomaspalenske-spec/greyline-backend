"""TradeStation quote STREAM as a cache-warmer: a streamed quote frame is written into the shared quote
cache in the exact shape get_quote/get_quotes serve, so callers read it verbatim as a fresh cache hit —
no network. Heartbeat/status/error frames never pollute the cache. Disabled => no thread. No real socket."""

import app.services.tradestation_quote_live_engine as qmod
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine as Q
from app.services.tradestation_quote_stream_engine import TradeStationQuoteStreamEngine as S


def _reset():
    Q._quote_cache.clear()
    S._state.update({"frames": 0, "last_frame_at": None, "last_error": None})


def test_streamed_quote_is_served_by_get_quote(monkeypatch):
    _reset()
    S._ingest({"Symbol": "SPY", "Last": 500.0, "Bid": 499.9, "Ask": 500.1})
    # get_quote must serve it straight from cache — prove it does NO network by nuking requests.get
    monkeypatch.setattr(qmod.TradeStationTokenMaintenanceEngine, "evaluate", lambda self: {})
    monkeypatch.setenv("TRADESTATION_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(qmod.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no net")))
    r = Q().get_quote("SPY")
    assert r["cache_hit"] is True and r.get("served_from_stream") is True
    assert r["response_json"]["Quotes"][0]["Last"] == 500.0


def test_streamed_quotes_served_by_batch():
    _reset()
    S._ingest({"Symbol": "SPY", "Last": 500.0})
    S._ingest({"Symbol": "QQQ", "Last": 400.0})
    out = Q().get_quotes(["SPY", "QQQ"])          # both cached -> returns before any network/token call
    assert out["SPY"]["cache_hit"] is True
    assert out["QQQ"]["response_json"]["Quotes"][0]["Last"] == 400.0


def test_heartbeat_status_error_frames_do_not_pollute_cache():
    _reset()
    S._ingest({"Heartbeat": 7})
    S._ingest({"StreamStatus": "Connected"})
    S._ingest({"Error": "boom"})
    assert Q._quote_cache == {}                    # none of these are quotes
    assert S._state["last_error"] == "boom"
    assert S._state["last_frame_at"] is not None   # heartbeat still proves the socket is alive


def test_ingest_ignores_symbolless_and_nondict():
    _reset()
    S._ingest({"Last": 1.0})                        # no Symbol
    S._ingest("not-a-dict")
    S._ingest(None)
    assert Q._quote_cache == {} and S._state["frames"] == 0


def test_symbols_cap_and_env_extend(monkeypatch):
    monkeypatch.setenv("GREYLINE_TS_STREAM_SYMBOLS", "AAPL, MSFT")
    monkeypatch.setenv("GREYLINE_TS_STREAM_MAX", "3")
    syms = S._symbols()
    assert len(syms) == 3 and syms[0] == "SPY"     # capped; core comes first
    monkeypatch.setenv("GREYLINE_TS_STREAM_MAX", "50")
    syms2 = S._symbols()
    assert "AAPL" in syms2 and "MSFT" in syms2 and len(syms2) == len(set(syms2))   # appended + deduped


def test_disabled_does_not_start(monkeypatch):
    monkeypatch.setenv("GREYLINE_TS_QUOTE_STREAM_ENABLED", "false")
    r = S.start_if_enabled()
    assert r["status"] == "STREAM_DISABLED"
    assert not (S._thread and S._thread.is_alive())


def test_status_shape():
    st = S.status()
    for k in ("status", "connected", "symbols", "frames", "alive", "enabled", "stale_seconds"):
        assert k in st


def test_partial_frame_without_price_is_dropped():
    # TS sends partial/delta frames; a price-less frame must NOT overwrite the cache (would be worse than
    # REST). Dropped -> caller falls back to REST until a real quote arrives.
    _reset()
    S._ingest({"Symbol": "DBC", "TradeTime": "2026-08-12T16:00:00Z"})
    assert "DBC" not in Q._quote_cache and S._state["frames"] == 0


def test_delta_frame_merges_onto_prior_price():
    # a later partial delta updates only the field it carries; last-known Last/Ask persist
    _reset()
    S._ingest({"Symbol": "SPY", "Last": 500.0, "Bid": 499.9, "Ask": 500.1})
    S._ingest({"Symbol": "SPY", "Bid": 499.95})
    row = Q._quote_cache["SPY"]["response_json"]["Quotes"][0]
    assert row["Bid"] == 499.95 and row["Last"] == 500.0 and row["Ask"] == 500.1
