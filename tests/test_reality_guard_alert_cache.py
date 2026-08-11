"""Reality Guard: (1) operator routes serve a cached verdict instead of the ~30s live recompute; the
scheduler force-refreshes it. (2) fantasy_alert() ACTIVATES the safety net — pages (deduped, off-machine)
on a true FANTASY_DETECTED, but NEVER on a degraded read (the guard's cry-wolf rule). The invariant compute
is stubbed — this tests the cache + alert contract, not the ~30 individual invariants."""

import pytest

import app.services.greyline_reality_guard_engine as mod
from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G


@pytest.fixture(autouse=True)
def _clear_guard_cache():
    # the guard cache is module-global — clear it around every test so state never leaks between tests
    mod._GUARD_CACHE["at"] = 0.0
    mod._GUARD_CACHE["result"] = None
    yield
    mod._GUARD_CACHE["at"] = 0.0
    mod._GUARD_CACHE["result"] = None


def _stub(monkeypatch, verdict, fantasy=None, degraded=None):
    fantasy = fantasy or []
    degraded = degraded or []
    calls = {"n": 0}
    checks = [{"id": i, "severity": "critical", "ok": False, "detail": f"{i} bad"} for i in (fantasy + degraded)]

    def _c(self):
        calls["n"] += 1
        return {"verdict": verdict, "fantasy_failures": list(fantasy), "degraded_failures": list(degraded),
                "critical_failures": list(fantasy + degraded), "warnings": [], "checks": checks, "_n": calls["n"]}

    monkeypatch.setattr(G, "_compute_check", _c)
    mod._GUARD_CACHE["at"] = 0.0
    mod._GUARD_CACHE["result"] = None
    return calls


class _AlertSpy:
    def __init__(self): self.sent = []
    def has_external_channel(self): return True
    def dispatch(self, **kw): self.sent.append(kw)


def _spy_alerts(monkeypatch):
    spy = _AlertSpy()
    import app.services.external_alert_engine as ae
    monkeypatch.setattr(ae, "ExternalAlertEngine", lambda: spy)
    return spy


def test_routes_served_from_cache(monkeypatch):
    monkeypatch.setenv("GREYLINE_REALITY_GUARD_CACHE_TTL_S", "150")
    calls = _stub(monkeypatch, "REAL_DATA_VERIFIED")
    first = G().check()
    assert calls["n"] == 1 and not first.get("served_from_cache")
    second = G().check()                       # warm -> no recompute (the 30s->instant win)
    assert calls["n"] == 1 and second["served_from_cache"] is True


def test_scheduler_force_fresh_warms_cache(monkeypatch):
    monkeypatch.setenv("GREYLINE_REALITY_GUARD_CACHE_TTL_S", "150")
    calls = _stub(monkeypatch, "REAL_DATA_VERIFIED")
    G().check()                                # n=1
    G().check(allow_cache=False)               # scheduler forces fresh -> n=2
    assert calls["n"] == 2
    assert G().check()["served_from_cache"] is True and calls["n"] == 2


def test_fantasy_pages_off_machine(monkeypatch):
    _stub(monkeypatch, "FANTASY_DETECTED", fantasy=["NO_PHANTOM_POSITIONS"])
    spy = _spy_alerts(monkeypatch)
    r = G().fantasy_alert()
    assert r["status"] == "REALITY_GUARD_FANTASY_FLAGGED" and r["fantasy"] == ["NO_PHANTOM_POSITIONS"]
    assert len(spy.sent) == 1
    assert spy.sent[0]["severity"] == "CRITICAL"
    assert spy.sent[0]["fingerprint"] == "REALITY_FANTASY:NO_PHANTOM_POSITIONS"


def test_degraded_read_never_pages(monkeypatch):
    # a degraded broker read is honest amber, NOT fantasy — must not cry wolf
    _stub(monkeypatch, "BROKER_READ_DEGRADED", degraded=["BROKER_READS_OK"])
    spy = _spy_alerts(monkeypatch)
    r = G().fantasy_alert()
    assert r["status"] == "REALITY_GUARD_NO_FANTASY" and r["fantasy"] == []
    assert spy.sent == []


def test_clean_state_never_pages(monkeypatch):
    _stub(monkeypatch, "REAL_DATA_VERIFIED")
    spy = _spy_alerts(monkeypatch)
    assert G().fantasy_alert()["status"] == "REALITY_GUARD_NO_FANTASY"
    assert spy.sent == []


def test_fantasy_dedup_fingerprint_is_stable_set(monkeypatch):
    # same failing set in any order -> same fingerprint (pages once per NEW state, not every cycle)
    _stub(monkeypatch, "FANTASY_DETECTED", fantasy=["EXEC_BOOKING_COHERENT", "NO_PHANTOM_POSITIONS"])
    spy = _spy_alerts(monkeypatch)
    G().fantasy_alert()
    assert spy.sent[0]["fingerprint"] == "REALITY_FANTASY:EXEC_BOOKING_COHERENT,NO_PHANTOM_POSITIONS"
