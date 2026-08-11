"""UnusualWhalesProvider._get resilience: SINGLE-FLIGHT (concurrent same-key callers coalesce into one
fetch, not a herd) + TOTAL-REQUEST DEADLINE (a trickling response body aborts instead of hanging the
caller — the 2026-08-11 scheduler-freeze class). Session is faked — no network."""

import json
import threading
import time

import pytest

import app.services.data_providers.unusual_whales_provider as mod
from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider as UW


class _FakeResp:
    def __init__(self, chunks, status=200, headers=None, per_chunk_sleep=0.0):
        self._chunks = chunks
        self.status_code = status
        self.headers = headers or {}
        self._sleep = per_chunk_sleep
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for c in self._chunks:
            if self._sleep:
                time.sleep(self._sleep)
            yield c

    def raise_for_status(self):
        if self.status_code >= 400:
            raise mod.requests.exceptions.HTTPError(str(self.status_code))

    def close(self):
        self.closed = True


def _provider(monkeypatch, response_factory, count):
    uw = UW.__new__(UW)                       # bypass __init__ (env/session/file side effects)
    uw.api_key = "test-key"

    class _FakeSession:
        def get(self, url, params=None, timeout=None, stream=False):
            count["n"] += 1
            return response_factory()

    uw.session = _FakeSession()
    monkeypatch.setattr(UW, "_consume_budget", lambda self: None)
    monkeypatch.setattr(UW, "_usage_state", lambda self: {})
    monkeypatch.setattr(UW, "_write_usage_state", lambda self, s: None)
    monkeypatch.setattr(UW, "_record_cache_hit", lambda self: None)
    monkeypatch.setattr(UW, "_ttl_for_path", lambda self, p: 60.0)
    UW._cache.clear()
    UW._inflight_locks.clear()
    return uw


def test_single_flight_coalesces_concurrent_same_key(monkeypatch):
    count = {"n": 0}
    body = json.dumps({"ok": 1}).encode()
    uw = _provider(monkeypatch, lambda: _FakeResp([body], per_chunk_sleep=0.2), count)
    results = []

    def call():
        results.append(uw._get("/x", {"t": "AAPL"}))

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results and all(r == {"ok": 1} for r in results)
    assert count["n"] == 1        # 8 concurrent same-key callers -> ONE fetch (no herd)


def test_total_deadline_aborts_a_trickling_body(monkeypatch):
    monkeypatch.setenv("GREYLINE_UW_TOTAL_DEADLINE", "0.5")
    count = {"n": 0}
    # 20 chunks x 0.2s each = 4s of body -> must abort at ~0.5s, not hang
    resp_holder = {}

    def factory():
        r = _FakeResp([b"x"] * 20, per_chunk_sleep=0.2)
        resp_holder["r"] = r
        return r

    uw = _provider(monkeypatch, factory, count)
    t0 = time.monotonic()
    with pytest.raises(mod.requests.exceptions.Timeout):
        uw._get("/slow", {"t": "X"})
    assert time.monotonic() - t0 < 2.0            # aborted quickly, did not read all 4s
    assert resp_holder["r"].closed is True         # connection released


def test_cache_fast_path_no_refetch(monkeypatch):
    count = {"n": 0}
    body = json.dumps({"v": 2}).encode()
    uw = _provider(monkeypatch, lambda: _FakeResp([body]), count)
    a = uw._get("/c", {"t": "A"})
    b = uw._get("/c", {"t": "A"})
    assert a == {"v": 2} and b == {"v": 2}
    assert count["n"] == 1                          # second call served from cache


def test_different_keys_do_not_block_each_other(monkeypatch):
    count = {"n": 0}
    body = json.dumps({"ok": 1}).encode()
    uw = _provider(monkeypatch, lambda: _FakeResp([body]), count)
    uw._get("/a", {"t": "A"})
    uw._get("/b", {"t": "B"})
    assert count["n"] == 2                          # distinct keys each fetch (no false coalescing)


def test_allow_forbidden_403_returns_none_and_caches(monkeypatch):
    count = {"n": 0}
    uw = _provider(monkeypatch, lambda: _FakeResp([b""], status=403), count)
    assert uw._get("/f", {"t": "A"}, allow_forbidden=True) is None
    assert uw._get("/f", {"t": "A"}, allow_forbidden=True) is None
    assert count["n"] == 1                          # the None (403) is cached, not re-fetched
