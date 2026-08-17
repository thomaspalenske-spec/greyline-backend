"""ttl_cached: short-TTL single-flight cache for read-only report methods — the fix for the dashboard
recomputing shadow/court routes on every poll (2026-08-16 CPU-peg incident)."""
import threading
import time

from app.services.ttl_cache import ttl_cached


class _Eng:
    def __init__(self):
        self.calls = 0

    @ttl_cached(30, env_key="GREYLINE_TEST_TTL")
    def report(self):
        self.calls += 1
        return {"n": self.calls}


def test_cache_hit_skips_recompute(monkeypatch):
    monkeypatch.setenv("GREYLINE_TEST_TTL", "30")
    e = _Eng()
    assert e.report()["n"] == 1
    assert e.report()["n"] == 1          # cached — not recomputed
    assert e.calls == 1


def test_shared_across_instances(monkeypatch):
    # self is excluded from the key, so all instances share one cached result (route makes a new engine each hit)
    monkeypatch.setenv("GREYLINE_TEST_TTL", "30")
    _Eng().report(); _Eng().report(); _Eng().report()
    total = _Eng.report._ttl_cache
    assert len(total) == 1               # one cache entry despite 3 instances


def test_ttl_zero_disables(monkeypatch):
    monkeypatch.setenv("GREYLINE_TEST_TTL", "0")
    _Eng.report._ttl_cache.clear()
    e = _Eng()
    e.report(); e.report()
    assert e.calls == 2                   # kill switch: every call recomputes


def test_single_flight_under_concurrency(monkeypatch):
    monkeypatch.setenv("GREYLINE_TEST_TTL", "30")

    class _Slow:
        def __init__(self): self.calls = 0
        @ttl_cached(30, env_key="GREYLINE_TEST_TTL")
        def report(self):
            self.calls += 1
            time.sleep(0.2)
            return self.calls

    holder = {"e": _Slow()}
    ts = [threading.Thread(target=holder["e"].report) for _ in range(20)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert holder["e"].calls == 1         # 20 concurrent pollers -> ONE recompute


def test_exception_not_cached(monkeypatch):
    monkeypatch.setenv("GREYLINE_TEST_TTL", "30")

    class _Boom:
        n = 0
        @ttl_cached(30, env_key="GREYLINE_TEST_TTL")
        def report(self):
            _Boom.n += 1
            raise ValueError("x")

    b = _Boom()
    for _ in range(2):
        try:
            b.report()
        except ValueError:
            pass
    assert _Boom.n == 2                    # a raising call is never cached
