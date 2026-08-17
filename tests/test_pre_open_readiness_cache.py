"""Pre-open readiness cache: the operator route serves a recent cached audit (instant) instead of the
30-50s contended live recompute; the scheduler forces a fresh compute to keep it warm. Only a real audit
is cached (never fabricated). The compute itself is stubbed — this tests the cache contract, not the probes."""

import app.services.pre_open_readiness_engine as mod
from app.services.pre_open_readiness_engine import PreOpenReadinessEngine as P


def _stub_compute(monkeypatch):
    calls = {"n": 0}

    def _c(self):
        calls["n"] += 1
        return {"overall": "READY", "checks": [], "fail_count": 0, "warn_count": 0, "_n": calls["n"]}

    monkeypatch.setattr(P, "_compute_audit", _c)
    mod._AUDIT_CACHE["at"] = 0.0
    mod._AUDIT_CACHE["result"] = None
    return calls


def test_route_reads_are_served_from_cache(monkeypatch):
    monkeypatch.setenv("GREYLINE_READINESS_CACHE_TTL_S", "150")
    calls = _stub_compute(monkeypatch)
    first = P().audit()                       # cold -> computes
    assert calls["n"] == 1 and not first.get("served_from_cache")
    second = P().audit()                      # warm -> cache, NO recompute (the 51s->instant win)
    assert calls["n"] == 1
    assert second["served_from_cache"] is True and second["cache_age_seconds"] is not None


def test_allow_cache_false_forces_fresh_and_warms(monkeypatch):
    monkeypatch.setenv("GREYLINE_READINESS_CACHE_TTL_S", "150")
    calls = _stub_compute(monkeypatch)
    P().audit()                               # cold compute (n=1)
    P().audit(allow_cache=False)              # scheduler forces fresh (n=2)
    assert calls["n"] == 2
    served = P().audit()                      # route now serves the fresh one, no recompute
    assert calls["n"] == 2 and served["served_from_cache"] is True


def test_stale_cache_recomputes(monkeypatch):
    monkeypatch.setenv("GREYLINE_READINESS_CACHE_TTL_S", "150")
    calls = _stub_compute(monkeypatch)
    P().audit()                               # n=1, cached at ~now
    mod._AUDIT_CACHE["at"] -= 1000            # age it past the TTL
    P().audit()                               # stale -> recompute (n=2)
    assert calls["n"] == 2


def test_ttl_zero_disables_cache(monkeypatch):
    monkeypatch.setenv("GREYLINE_READINESS_CACHE_TTL_S", "0")
    calls = _stub_compute(monkeypatch)
    P().audit(); P().audit()
    assert calls["n"] == 2                     # every call recomputes when disabled
