"""VRP cycle-speed: parallel realized-vol series prefetch. rich_iv_candidates screens the whole universe
with a serial UW /volatility/realized call per name (measured ~57s) — the dominant VRP-cycle cost.
_prefetch_series warms that cache CONCURRENTLY so the screen loop hits cache. Behavior-preserving."""

import threading
import time

from app.services.conditional_vrp_forward_panel_engine import ConditionalVRPForwardPanelEngine as Pnl


def test_prefetch_series_calls_once_per_unique(monkeypatch):
    seen, lock = [], threading.Lock()
    def _grab(self, t):
        with lock:
            seen.append(t)
        return []
    monkeypatch.setattr(Pnl, "_fresh_series", _grab)
    Pnl()._prefetch_series(["IWM", "SMH", "XLE", "IWM"])       # dup -> once
    assert sorted(seen) == ["IWM", "SMH", "XLE"]


def test_prefetch_series_runs_concurrently(monkeypatch):
    monkeypatch.setattr(Pnl, "_fresh_series", lambda self, t: (time.sleep(0.2), [])[1])
    t0 = time.time()
    Pnl()._prefetch_series(["A", "B", "C", "D", "E", "F", "G", "H"])   # 8 x 0.2s serial = 1.6s
    assert time.time() - t0 < 0.8                              # parallel (<=8 workers) ~= 0.2s


def test_prefetch_series_single_is_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(Pnl, "_fresh_series", lambda self, t: calls.append(t) or [])
    Pnl()._prefetch_series(["IWM"])
    assert calls == []


def test_prefetch_series_best_effort_on_error(monkeypatch):
    def _boom(self, t):
        if t == "BAD":
            raise RuntimeError("uw down")
        return []
    monkeypatch.setattr(Pnl, "_fresh_series", _boom)
    Pnl()._prefetch_series(["IWM", "BAD", "SMH"])              # must not raise


def test_rich_iv_candidates_prefetches_then_screens(monkeypatch):
    # prove the screen still runs and prefetch was invoked with the universe, before the loop.
    prefetched = []
    monkeypatch.setattr(Pnl, "_prefetch_series", lambda self, names, workers=8: prefetched.extend(names))
    # deterministic series: one rich-IV name that passes, one that fails length
    def _series(self, t):
        if t == "RICH":
            return [{"date": "2026-0%d-01" % (i % 9 + 1), "implied_volatility": 0.5,
                     "unshifted_rv_date": "2026-09-01"} for i in range(70)]
        return []
    monkeypatch.setattr(Pnl, "_fresh_series", _series)
    eng = Pnl()
    monkeypatch.setattr(type(eng).__mro__[0], "_fresh_series", _series)
    monkeypatch.setattr(eng.vrp.__class__, "DEFAULT_NAMES", ["RICH", "THIN"], raising=False)
    monkeypatch.setattr(eng.cvrp, "_trailing_rank", lambda ivs, i, lb: 0.95)
    monkeypatch.setattr(eng.cvrp, "_earnings_dates", lambda t: [])
    monkeypatch.setattr(eng.cvrp, "THRESHOLD", 0.5, raising=False)
    out = eng.rich_iv_candidates(["RICH", "THIN"])
    assert prefetched == ["RICH", "THIN"]                      # prefetched the universe first
    assert [c["ticker"] for c in out] == ["RICH"]             # THIN dropped (series too short)
