"""VRP cycle-speed: parallel chain prefetch. plan() fetches a chain per candidate serially (2 UW calls at
up to 20s each) — the dominant VRP-cycle cost. _prefetch_chains warms the cache CONCURRENTLY so the build
loop hits cache. Behavior-preserving (same _chain path); only the network fetches overlap."""

import threading
import time

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def test_prefetch_calls_chain_once_per_unique_ticker(monkeypatch):
    seen = []
    lock = threading.Lock()
    monkeypatch.setattr(V, "_chain", lambda self, t: (lock.acquire(), seen.append(t), lock.release(), ("2026-09-18", []))[-1])
    V()._prefetch_chains(["IWM", "SMH", "XLE", "IWM"])          # dup IWM -> fetched once
    assert sorted(seen) == ["IWM", "SMH", "XLE"]


def test_prefetch_runs_concurrently(monkeypatch):
    # each _chain sleeps 0.2s; 6 tickers serial = 1.2s, parallel (<=6 workers) ~= 0.2s
    def _slow(self, t):
        time.sleep(0.2)
        return ("2026-09-18", [])
    monkeypatch.setattr(V, "_chain", _slow)
    t0 = time.time()
    V()._prefetch_chains(["A", "B", "C", "D", "E", "F"])
    elapsed = time.time() - t0
    assert elapsed < 0.7                                        # nowhere near the 1.2s serial cost


def test_prefetch_single_ticker_is_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(V, "_chain", lambda self, t: calls.append(t) or ("2026-09-18", []))
    V()._prefetch_chains(["IWM"])                              # <=1 unique -> skip the pool entirely
    assert calls == []


def test_prefetch_is_best_effort_on_error(monkeypatch):
    def _boom(self, t):
        if t == "BAD":
            raise RuntimeError("chain down")
        return ("2026-09-18", [])
    monkeypatch.setattr(V, "_chain", _boom)
    # must not raise even though one ticker errors
    V()._prefetch_chains(["IWM", "BAD", "SMH"])


def test_plan_prefetches_then_builds_off_cache(monkeypatch):
    # end-to-end: plan() prefetches the candidate pool, then the loop builds off the (now warm) chains.
    import app.services.conditional_vrp_forward_panel_engine as panel_mod
    monkeypatch.setattr(panel_mod.ConditionalVRPForwardPanelEngine, "rich_iv_candidates",
                        lambda self, names=None: [{"ticker": t, "iv_rank": 55, "iv": 0.3} for t in ("IWM", "SMH", "XLE")])
    monkeypatch.setattr(V, "_open_symbols", lambda self: set())
    monkeypatch.setattr(V, "_open_risk", lambda self: 0.0)
    monkeypatch.setattr(V, "_vega_budget", classmethod(lambda cls: 1e9))
    monkeypatch.setattr(V, "_current_book_vega", lambda self: 0.0)
    prefetched = []
    monkeypatch.setattr(V, "_prefetch_chains", lambda self, tickers, workers=6: prefetched.extend(tickers))
    monkeypatch.setattr(V, "_chain", lambda self, t: ("2026-09-18", ["c"]))
    monkeypatch.setattr(V, "build_condor",
                        lambda self, sym, contracts, put_delta=None, call_delta=None, max_loss_cap=None:
                        {"symbol": sym, "quantity": 1, "credit_per_condor": 1.0, "credit_total": 100.0,
                         "max_loss_total": 400.0, "return_on_risk": 0.25, "net_vega": -5.0})
    pl = V().plan()
    # the prefetch was called with the candidate tickers BEFORE the build loop ran
    assert set(prefetched) == {"IWM", "SMH", "XLE"}
    assert len(pl["planned"]) >= 1                             # still builds the same condors
