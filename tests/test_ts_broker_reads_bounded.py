"""Broker read engines (balance/positions/orders) now fetch via http_bounded.bounded_get: a trickling TS
response DEGRADES (http_status None, *_READ_FAILED) instead of hanging the caller, and a good read parses
from the streamed body. Full trickle-immunity beyond the snapshot's single-flight. Network faked."""

import json
import time

import pytest
import requests

import app.services.tradestation_account_source_engine as smod
import app.services.tradestation_orders_live_engine as omod
import app.services.tradestation_balance_live_engine as bmod
import app.services.tradestation_positions_live_engine as pmod
from app.services.tradestation_orders_live_engine import TradeStationOrdersLiveEngine
from app.services.tradestation_balance_live_engine import TradeStationBalanceLiveEngine
from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine


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
    for m in (omod, bmod, pmod):
        monkeypatch.setattr(m, "reload_env", lambda: None)
    monkeypatch.setenv("TRADESTATION_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(smod.TradeStationAccountSourceEngine, "resolve",
                        lambda self: {"ok": True, "account_id": "SIM1", "mode": "paper",
                                      "host_kind": "sim", "base_url": "https://sim-api.tradestation.com"})
    TradeStationBalanceLiveEngine._CACHE.clear()
    TradeStationPositionsLiveEngine._CACHE.clear()
    yield


def _trickle(*a, **k):
    return _FakeResp([b"x"] * 20, per_chunk_sleep=0.2)     # ~4s of body


def test_orders_trickle_degrades_not_hangs(monkeypatch):
    monkeypatch.setenv("GREYLINE_TS_BROKER_DEADLINE", "0.5")
    monkeypatch.setattr(requests, "get", _trickle)
    t0 = time.monotonic()
    r = TradeStationOrdersLiveEngine().get_orders()
    assert time.monotonic() - t0 < 2.0                     # aborted at the deadline
    assert r["http_status"] is None and r["status"] == "ORDERS_READ_FAILED"


def test_orders_good_read_parses(monkeypatch):
    body = json.dumps({"Orders": [{"OrderID": "1"}]}).encode()
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResp([body]))
    r = TradeStationOrdersLiveEngine().get_orders()
    assert r["http_status"] == 200 and r["response_json"]["Orders"][0]["OrderID"] == "1"


def test_balance_trickle_degrades(monkeypatch):
    monkeypatch.setenv("GREYLINE_TS_BROKER_DEADLINE", "0.5")
    monkeypatch.setattr(requests, "get", _trickle)
    r = TradeStationBalanceLiveEngine().get_balance()
    assert r["http_status"] is None and r["status"] == "BALANCE_READ_FAILED"


def test_positions_good_read_parses_and_caches(monkeypatch):
    body = json.dumps({"Positions": [{"Symbol": "USMV", "Quantity": "3"}]}).encode()
    count = {"n": 0}

    def _get(*a, **k):
        count["n"] += 1
        return _FakeResp([body])

    monkeypatch.setattr(requests, "get", _get)
    a = TradeStationPositionsLiveEngine().get_positions()
    b = TradeStationPositionsLiveEngine().get_positions()
    assert a["http_status"] == 200 and a["response_json"]["Positions"][0]["Symbol"] == "USMV"
    assert b.get("served_from_cache") is True and count["n"] == 1     # 200 cached; trickle-immunity intact
