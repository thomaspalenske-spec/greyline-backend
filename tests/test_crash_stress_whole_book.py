"""Whole-book crash scenario: the three loss channels combine correctly (equity directional + SVXY
non-linear crash + condor vega), cash-equivalents are excluded, and a degraded broker read is flagged
(not silently reported as a calm zero-loss book). Deterministic — positions and greeks are stubbed."""

import pytest

from app.services.crash_stress_test_engine import CrashStressTestEngine as C


@pytest.fixture
def book(monkeypatch):
    monkeypatch.setattr(C, "_live_equity_positions",
                        lambda self: [("SPY", 5000.0), ("SVXY", 2000.0), ("SGOV", 1000.0)])
    from app.services.portfolio_greeks_engine import PortfolioGreeksEngine
    monkeypatch.setattr(PortfolioGreeksEngine, "book_greeks", lambda self: {"net_vega": 0.0})


def test_holdings_split_excludes_cash_equiv(book):
    h = C().stress_whole_book()["holdings"]
    assert h["long_equity_usd"] == 5000 and h["svxy_usd"] == 2000 and h["cash_equiv_usd"] == 1000


def test_black_monday_decomposition(book):
    r = C().stress_whole_book()
    bm = next(s for s in r["scenarios"] if s["scenario"].startswith("Black Monday"))
    assert bm["equity_directional_usd"] == -1000     # 5000 x 1.0 x -0.20
    assert bm["svxy_crash_usd"] == -1900             # 2000 x -0.95 (non-linear, not beta x index)
    assert bm["short_vol_vega_usd"] == 0             # net_vega stubbed to 0
    assert bm["total_usd"] == -2900
    assert r["worst_case"]["scenario"].startswith("Black Monday")


def test_svxy_is_the_sharpest_tail(book):
    bm = next(s for s in C().stress_whole_book()["scenarios"] if s["scenario"].startswith("Black Monday"))
    assert abs(bm["svxy_crash_usd"]) > abs(bm["equity_directional_usd"])


def test_moderate_scare_is_shallower_than_black_monday(book):
    rows = {s["scenario"]: s["total_usd"] for s in C().stress_whole_book()["scenarios"]}
    mod = next(v for k, v in rows.items() if k.startswith("Moderate"))
    bm = next(v for k, v in rows.items() if k.startswith("Black Monday"))
    assert mod > bm                                   # less negative = shallower


def test_positive_or_flipped_vega_never_becomes_a_gain(monkeypatch):
    # regression: an unstable live net_vega that reads POSITIVE must NOT manufacture a "gain" in a crash —
    # the short-vol contribution is clamped to <= 0.
    monkeypatch.setattr(C, "_live_equity_positions",
                        lambda self: [("SPY", 5000.0), ("SVXY", 2000.0)])
    from app.services.portfolio_greeks_engine import PortfolioGreeksEngine
    monkeypatch.setattr(PortfolioGreeksEngine, "book_greeks", lambda self: {"net_vega": +180.0})
    r = C().stress_whole_book()
    for s in r["scenarios"]:
        assert s["short_vol_vega_usd"] <= 0                 # never a gain in a crash
        assert s["total_usd"] < 0                           # every crash scenario is a net LOSS
    assert r["worst_case"]["total_usd"] < 0


def test_degraded_read_is_flagged_not_calm(monkeypatch):
    monkeypatch.setattr(C, "_live_equity_positions", lambda self: None)
    r = C().stress_whole_book()
    assert r["read_ok"] is False                      # truth: we could not read the book
    assert r["holdings"]["long_equity_usd"] == 0
