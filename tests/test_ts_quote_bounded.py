"""TradeStationQuoteLiveEngine bounded reads: SINGLE-FLIGHT (concurrent identical quote fetches coalesce)
+ TOTAL-REQUEST DEADLINE (a trickling TS response degrades instead of hanging the cycle) + cache. Network
faked via requests.get; no real broker calls."""

import json
import threading
import time

import pytest
import requests

import app.services.tradestation_quote_live_engine as qmod
from app.services.http_bounded import KeyedSingleFlight
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine as Q


class _FakeResp:
    def __init__(self, chunks, status=200, per_chunk_sleep=0.0):
        self._chunks = chunks
        self.status_code = status
        self.headers = {}
        self._sleep = per_chunk_sleep
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for c in self._chunks:
            if self._sleep:
                time.sleep(self._sleep)
            yield c

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    monkeypatch.setattr(qmod, "reload_env", lambda: None)
    monkeypatch.setattr(qmod.TradeStationTokenMaintenanceEngine, "evaluate", lambda self: {})
    monkeypatch.setenv("TRADESTATION_ACCESS_TOKEN", "tok")
    Q._quote_cache.clear()
    Q._SF = KeyedSingleFlight()
    yield


def _quotes_get(count, sleep=0.0):
    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        count["n"] += 1
        syms = url.rsplit("/", 1)[1].split(",")
        body = json.dumps({"Quotes": [{"Symbol": s, "Last": 10.0} for s in syms]}).encode()
        return _FakeResp([body], per_chunk_sleep=sleep)
    return fake_get


def test_batch_single_flight_coalesces(monkeypatch):
    count = {"n": 0}
    monkeypatch.setattr(requests, "get", _quotes_get(count, sleep=0.2))
    results = []

    def call():
        results.append(Q().get_quotes(["AAPL", "MSFT"]))

    threads = [threading.Thread(target=call) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert count["n"] == 1        # 6 concurrent identical batches -> ONE fetch
    assert all(r["AAPL"]["response_json"]["Quotes"][0]["Last"] == 10.0 for r in results)


def test_batch_total_deadline_degrades_not_hangs(monkeypatch):
    monkeypatch.setenv("GREYLINE_TS_QUOTE_DEADLINE", "0.5")
    holder = {}

    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        r = _FakeResp([b"x"] * 20, per_chunk_sleep=0.2)   # ~4s trickle
        holder["r"] = r
        return r

    monkeypatch.setattr(requests, "get", fake_get)
    t0 = time.monotonic()
    out = Q().get_quotes(["AAPL"])
    assert time.monotonic() - t0 < 2.0                     # aborted at the deadline, did not read 4s
    assert out["AAPL"]["status"] == "QUOTE_READ_FAILED"
    assert holder["r"].closed is True


def test_batch_cache_served_without_refetch(monkeypatch):
    count = {"n": 0}
    monkeypatch.setattr(requests, "get", _quotes_get(count))
    Q().get_quotes(["AAPL"])
    Q().get_quotes(["AAPL"])
    assert count["n"] == 1                                  # second served from the 60s cache


def test_single_quote_deadline_degrades(monkeypatch):
    monkeypatch.setenv("GREYLINE_TS_QUOTE_DEADLINE", "0.5")

    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        return _FakeResp([b"x"] * 20, per_chunk_sleep=0.2)

    monkeypatch.setattr(requests, "get", fake_get)
    r = Q().get_quote("AAPL")
    assert r["status"] == "QUOTE_READ_FAILED"


def test_single_quote_success_and_caches(monkeypatch):
    count = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        count["n"] += 1
        sym = url.rsplit("/", 1)[1]
        return _FakeResp([json.dumps({"Quotes": [{"Symbol": sym, "Last": 7.0}]}).encode()])

    monkeypatch.setattr(requests, "get", fake_get)
    a = Q().get_quote("AAPL")
    b = Q().get_quote("AAPL")
    assert a["status"] == "QUOTE_READ_SUCCESS" and a["response_json"]["Quotes"][0]["Last"] == 7.0
    assert b["cache_hit"] is True and count["n"] == 1
