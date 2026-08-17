"""TS brokerage positions stream cache-warmer. The safety contract under test: the stream warms the
shared positions cache ONLY while a cache-bypassing REST cross-check agrees; any mismatch, book change,
or disable refuses to warm so callers fall back to REST. Fully hermetic — no network, no broker."""

import time

import pytest

from app.services.tradestation_broker_stream_engine import TradeStationBrokerStreamEngine as B
from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine as P


@pytest.fixture(autouse=True)
def _reset():
    B._mirror = {}
    B._account = "SIMTEST"
    B._src = {"mode": "paper", "host_kind": "sim"}
    B._synced = False
    B._snapshot_complete = False
    B._last_crosscheck = None
    B._last_crosscheck_mono = 0.0
    B._state = dict(B._state, frames=0, warm_writes=0, last_frame_at=None, last_error=None)
    P._CACHE.clear()
    yield
    P._CACHE.clear()


def _pos(pid, sym, qty, side="Long"):
    return {"PositionID": pid, "Symbol": sym, "Quantity": str(qty), "LongShort": side}


def test_signed_qty_and_aggregation():
    B._mirror = {"1": _pos("1", "IWM", 4), "2": _pos("2", "SVXY", 38),
                 "3": _pos("3", "VXX", 10, side="Short")}
    agg = B._mirror_by_symbol()
    assert agg == {"IWM": 4.0, "SVXY": 38.0, "VXX": -10.0}   # Short -> negative


def test_crosscheck_syncs_only_on_agreement(monkeypatch):
    B._mirror = {"1": _pos("1", "IWM", 4), "2": _pos("2", "QQQM", 8)}
    # REST agrees -> synced
    monkeypatch.setattr(B, "_rest_by_symbol", classmethod(lambda cls: {"IWM": 4.0, "QQQM": 8.0}))
    B._crosscheck()
    assert B._synced is True and B._last_crosscheck["ok"] is True
    # REST now disagrees (a position the stream missed) -> desynced, mismatch reported
    monkeypatch.setattr(B, "_rest_by_symbol", classmethod(lambda cls: {"IWM": 4.0, "QQQM": 8.0, "SPY": 3.0}))
    B._crosscheck()
    assert B._synced is False and "SPY" in B._last_crosscheck["mismatch"]


def test_crosscheck_refuses_when_rest_unavailable(monkeypatch):
    B._mirror = {"1": _pos("1", "IWM", 4)}
    monkeypatch.setattr(B, "_rest_by_symbol", classmethod(lambda cls: None))
    B._crosscheck()
    assert B._synced is False and B._last_crosscheck["reason"] == "REST_UNAVAILABLE"


def test_warm_writes_cache_only_when_synced():
    B._mirror = {"1": _pos("1", "IWM", 4)}
    B._synced = False
    B._warm()
    assert "SIMTEST" not in P._CACHE                  # desynced -> never warm
    B._synced = True
    B._warm()
    assert "SIMTEST" in P._CACHE
    ts, result = P._CACHE["SIMTEST"]
    assert result["status"] == "POSITIONS_READ_SUCCESS" and result["served_from_stream"] is True
    assert result["response_json"]["Positions"][0]["Symbol"] == "IWM"   # REST-shaped payload


def test_ingest_snapshot_then_heartbeat_syncs_and_warms(monkeypatch):
    monkeypatch.setattr(B, "_rest_by_symbol", classmethod(lambda cls: {"IWM": 4.0, "QQQM": 8.0}))
    B._ingest(_pos("1", "IWM", 4))
    B._ingest(_pos("2", "QQQM", 8))
    assert B._snapshot_complete is False and len(B._mirror) == 2
    B._ingest({"Heartbeat": 1})                       # end of snapshot -> crosscheck + warm
    assert B._snapshot_complete is True and B._synced is True
    assert P._CACHE["SIMTEST"][1]["response_json"]["Positions"]  # warmed


def test_post_snapshot_change_desyncs_until_reverified(monkeypatch):
    monkeypatch.setattr(B, "_rest_by_symbol", classmethod(lambda cls: B._mirror_by_symbol()))
    B._ingest(_pos("1", "IWM", 4))
    B._ingest({"Heartbeat": 1})
    assert B._synced is True
    B._ingest(_pos("2", "SPY", 3))                    # book changed after snapshot
    assert B._synced is False                         # must not warm a book REST hasn't re-confirmed
    B._ingest({"Heartbeat": 2})                       # re-check (REST mirrors current book) -> re-synced
    assert B._synced is True


def test_ingest_delete_removes_position():
    B._ingest(_pos("1", "IWM", 4))
    assert "1" in B._mirror
    B._ingest({"PositionID": "1", "Symbol": "IWM", "Quantity": "0", "LongShort": "Long"})
    assert "1" not in B._mirror                       # Quantity 0 -> removed


def test_disabled_start_is_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_TS_BROKER_STREAM_ENABLED", "false")
    assert B.start_if_enabled()["status"] == "BROKER_STREAM_DISABLED"


def test_positions_bypass_cache_does_not_read_or_write_cache(monkeypatch):
    # cross-check MUST read ground-truth REST, never the stream-warmed cache entry (circularity)
    P._CACHE["SIMTEST"] = (time.monotonic(), {"status": "POSITIONS_READ_SUCCESS",
                                              "response_json": {"Positions": [_pos("x", "STALE", 99)]},
                                              "served_from_stream": True})
    calls = {"n": 0}

    def _fake_resolve(self):
        return {"ok": True, "account_id": "SIMTEST", "base_url": "http://x", "mode": "paper", "host_kind": "sim"}

    def _fake_bounded_get(reqmod, url, **kw):
        calls["n"] += 1

        class _R:
            status_code = 200
        return _R(), b'{"Positions": [{"PositionID":"y","Symbol":"FRESH","Quantity":"1","LongShort":"Long"}]}'

    monkeypatch.setenv("TRADESTATION_ACCESS_TOKEN", "t")
    monkeypatch.setattr("app.services.tradestation_account_source_engine.TradeStationAccountSourceEngine.resolve",
                        _fake_resolve)
    monkeypatch.setattr("app.services.tradestation_positions_live_engine.bounded_get", _fake_bounded_get)
    res = P().get_positions(bypass_cache=True)
    assert calls["n"] == 1                                   # did a real REST read, ignored the cache
    assert res["response_json"]["Positions"][0]["Symbol"] == "FRESH"
    # and it did NOT overwrite the existing (stream) cache entry
    assert P._CACHE["SIMTEST"][1]["response_json"]["Positions"][0]["Symbol"] == "STALE"
