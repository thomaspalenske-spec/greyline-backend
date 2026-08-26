"""Cross-source price reconciliation ABS_TICK_FLOOR (2026-08-26): our CSVs store penny-rounded closes and two
vendors' daily closes differ by ~a tick, so on a sub-$1 stock that half-cent is ~1% and would trip the 0.10%
TOLERANCE_PCT every day — a false SYSTEMATIC_MISMATCH (the CGTX cry-wolf: 18/120 "bad", median_ratio 1.0012).
The absolute floor suppresses that while a REAL split/shift (many cents, median ratio far off 1.0) still fires."""

import pytest

from app.services.price_bar_cross_source_engine import PriceBarCrossSourceEngine as X


def _dates(n):
    return [f"2026-{1 + i // 20:02d}-{1 + i % 20:02d}" for i in range(n)]


def _run_with(monkeypatch, ours, live):
    monkeypatch.setenv("TRADESTATION_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr(X, "_csv_closes", lambda self, s: ours)
    from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine as M
    monkeypatch.setattr(M, "_fetch_daily_closes", lambda self, s, base, token: live)
    return X().reconcile(symbols=["TEST"], save=False)


def test_subdollar_penny_rounding_is_a_match(monkeypatch):
    ds = _dates(120)
    live = {d: 0.5946 for d in ds}          # full-precision feed
    ours = {d: 0.59 for d in ds}            # our penny-rounded store — 0.77% dev but only a half-cent
    res = _run_with(monkeypatch, ours, live)
    rec = res["results"][0]
    assert rec["verdict"] == "MATCH", rec
    assert rec["bad_days"] == 0


def test_real_unadjusted_split_still_flags(monkeypatch):
    ds = _dates(120)
    live = {d: 50.0 for d in ds}            # split-adjusted
    ours = {d: 100.0 for d in ds}           # our CSV never applied the 2:1 split — $50 gap, ratio 2.0
    res = _run_with(monkeypatch, ours, live)
    rec = [r for r in res["results"] if r.get("verdict") != "MATCH"][0]
    assert rec["verdict"] == "UNADJUSTED_SPLIT_SUSPECTED"
    assert rec["median_ratio"] == 2.0


def test_real_systematic_shift_still_flags(monkeypatch):
    ds = _dates(120)
    live = {d: 50.0 for d in ds}
    ours = {d: 55.0 for d in ds}            # consistent 10% / $5 gap — not split-like, well beyond the tick floor
    res = _run_with(monkeypatch, ours, live)
    rec = [r for r in res["results"] if r.get("verdict") != "MATCH"][0]
    assert rec["verdict"] == "SYSTEMATIC_MISMATCH"


def test_floor_is_one_cent():
    assert X.ABS_TICK_FLOOR == 0.01
