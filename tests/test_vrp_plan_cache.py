"""Shared per-cycle plan cache: read-only consumers (best-condors card, condor shadow) reuse the plan the
sleeve already built this cycle instead of a 2-3x redundant rebuild. The BOOKING path (plan() direct)
always recomputes, so what gets traded is never a stale plan."""

import time
from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def test_plan_cached_reuses_fresh_cache(monkeypatch):
    calls = {"n": 0}
    def fake_plan(self, **kw):
        calls["n"] += 1
        return {"planned": ["FRESH"], "status": "VRP_SHORT_PREMIUM_PLAN"}
    monkeypatch.setattr(V, "plan", fake_plan)

    monkeypatch.setattr(V, "_PLAN_CACHE", {"epoch": 0.0, "result": None})       # cold
    V().plan_cached()
    assert calls["n"] == 1                                                       # cold -> computed once

    monkeypatch.setattr(V, "_PLAN_CACHE", {"epoch": time.time(), "result": {"planned": ["CACHED"]}})
    r = V().plan_cached()
    assert r.get("cache_reused") is True and r["planned"] == ["CACHED"]
    assert calls["n"] == 1                                                       # fresh cache -> NOT recomputed


def test_plan_cached_recomputes_when_stale(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(V, "plan", lambda self, **kw: calls.__setitem__("n", calls["n"] + 1) or {"planned": []})
    monkeypatch.setattr(V, "_PLAN_CACHE", {"epoch": time.time() - 9999, "result": {"planned": ["OLD"]}})
    V().plan_cached()
    assert calls["n"] == 1                                                       # stale -> recomputed


def test_default_args_plan_populates_cache(monkeypatch):
    # a default-args plan() must SEED the cache so the read-only consumers can reuse it. Stub the whole
    # body via rich_iv_candidates=[] so plan() returns fast without broker/chain work.
    import app.services.conditional_vrp_forward_panel_engine as pm
    monkeypatch.setattr(pm.ConditionalVRPForwardPanelEngine, "rich_iv_candidates", lambda self, names=None: [])
    monkeypatch.setattr(V, "_open_symbols", lambda self: set())
    monkeypatch.setattr(V, "_open_risk", lambda self: 0.0)
    monkeypatch.setattr(V, "_prefetch_chains", lambda self, syms: None)
    monkeypatch.setattr(type(V()), "PORTFOLIO_RISK_CAP_USD", 1000.0, raising=False)
    monkeypatch.setattr(V, "_vega_budget", lambda self: 1000.0)
    monkeypatch.setattr(V, "_current_book_vega", lambda self: 0.0)
    monkeypatch.setattr(V, "_PLAN_CACHE", {"epoch": 0.0, "result": None})
    out = V().plan()
    assert out["status"] == "VRP_SHORT_PREMIUM_PLAN"
    assert V._PLAN_CACHE["result"] is not None and V._PLAN_CACHE["epoch"] > 0    # cache seeded
