"""Short-TTL single-flight cache on TradeStationSimBookingEngine._read — the fix for the dashboard
thundering-herd that pegged a core + starved the broker read/deadman (2026-08-16). A refresh burst of
N concurrent orders()/positions() calls must collapse to ONE upstream fetch per kind.
"""
import threading
import time

import pytest

from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine as E


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    E._invalidate_reads()
    monkeypatch.setattr(E, "_assert_sim", lambda self: "SIM123")
    yield
    E._invalidate_reads()


def _engine_counting(monkeypatch, delay=0.0):
    """An engine whose _request counts upstream fetches (and can be slowed to force concurrency)."""
    e = E()
    calls = {"n": 0}

    class _Resp:
        status_code = 200
        def json(self): return {"Orders": []}

    def fake_request(method, url, **k):
        calls["n"] += 1
        if delay:
            time.sleep(delay)
        return _Resp()

    monkeypatch.setattr(e, "_request", fake_request)
    return e, calls


def test_cache_hit_skips_network(monkeypatch):
    monkeypatch.setenv("GREYLINE_BROKER_READ_CACHE_TTL", "5")
    e, calls = _engine_counting(monkeypatch)
    e.orders(); e.orders(); e.orders()
    assert calls["n"] == 1                     # 3 calls, 1 fetch (cache hits)


def test_distinct_kinds_cached_separately(monkeypatch):
    monkeypatch.setenv("GREYLINE_BROKER_READ_CACHE_TTL", "5")
    e, calls = _engine_counting(monkeypatch)
    e.orders(); e.positions(); e.balances(); e.orders()
    assert calls["n"] == 3                     # one per kind; the 2nd orders() is a hit


def test_single_flight_collapses_concurrent_burst(monkeypatch):
    # 20 threads hit orders() at once while the fetch is slow -> must be ONE upstream call, not 20
    monkeypatch.setenv("GREYLINE_BROKER_READ_CACHE_TTL", "5")
    e, calls = _engine_counting(monkeypatch, delay=0.3)
    threads = [threading.Thread(target=e.orders) for _ in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert calls["n"] == 1                     # the thundering herd collapsed


def test_ttl_zero_disables_cache(monkeypatch):
    monkeypatch.setenv("GREYLINE_BROKER_READ_CACHE_TTL", "0")
    e, calls = _engine_counting(monkeypatch)
    e.orders(); e.orders()
    assert calls["n"] == 2                     # kill switch: every call fetches


def test_invalidate_forces_refetch(monkeypatch):
    monkeypatch.setenv("GREYLINE_BROKER_READ_CACHE_TTL", "5")
    e, calls = _engine_counting(monkeypatch)
    e.orders()
    E._invalidate_reads()
    e.orders()
    assert calls["n"] == 2                     # post-trade invalidation gives a fresh read


def test_failed_read_not_cached(monkeypatch):
    monkeypatch.setenv("GREYLINE_BROKER_READ_CACHE_TTL", "5")
    e = E()
    calls = {"n": 0}

    class _Resp:
        status_code = 503
        def json(self): return None

    monkeypatch.setattr(e, "_request", lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), _Resp())[1])
    e.orders(); e.orders()
    assert calls["n"] == 2                     # a transient failure is never pinned in the cache
