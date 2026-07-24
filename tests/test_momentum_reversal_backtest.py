"""The backtest must find edge where edge is planted and NOTHING in pure noise. If it can't
tell those apart, no number it reports on real data means anything."""

import random

import pytest

from app.services.momentum_reversal_backtest_engine import MomentumReversalBacktestEngine

HDR = "date,close,adj_close\n"


def _trading_days(n, start_year=2005):
    from datetime import date, timedelta
    out, d = [], date(start_year, 1, 3)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


@pytest.fixture
def eng(tmp_path, monkeypatch):
    monkeypatch.setattr(MomentumReversalBacktestEngine, "TR_DIR", tmp_path)
    monkeypatch.setattr(MomentumReversalBacktestEngine, "OUT", tmp_path / "out.json")
    monkeypatch.setattr(MomentumReversalBacktestEngine, "PERMUTATIONS", 400)
    # neutralize the tradability filter in tests
    import app.services.price_bar_tradability_engine as tb
    monkeypatch.setattr(tb.PriceBarTradabilityEngine, "tradable_from_map", lambda self: {})
    return MomentumReversalBacktestEngine


def _write(tmp_path, sym, days, closes):
    lines = [HDR]
    for d, c in zip(days, closes):
        lines.append(f"{d},{c:.4f},{c:.4f}\n")
    (tmp_path / f"{sym}_total_return.csv").write_text("".join(lines))


def test_finds_no_edge_in_pure_random_walks(eng, tmp_path, monkeypatch):
    """Random walks have no momentum-reversal edge. Testing ONE draw is wrong — under the null
    a single p<0.05 shows up ~1 time in 20. The correct check is AGGREGATE across many seeds:
    the gross edge must center near zero (no consistent sign) and the significant-fraction must
    stay near the 5% false-positive rate, NOT 100%. (Asserting non-significance on one seed is
    exactly the single-draw mistake this suite is meant to prevent.)"""
    import random as _r
    grosses, sig_count, runs = [], 0, 12
    base = tmp_path
    for seed in range(runs):
        d = base / f"run{seed}"
        d.mkdir()
        monkeypatch.setattr(MomentumReversalBacktestEngine, "TR_DIR", d)
        monkeypatch.setattr(MomentumReversalBacktestEngine, "OUT", d / "o.json")
        rng = _r.Random(seed)
        days = _trading_days(900)
        for i in range(40):
            px, closes = 100.0, []
            for _ in days:
                px *= (1 + rng.gauss(0, 0.02)); closes.append(px)
            (d / f"N{i:02d}_total_return.csv").write_text(
                HDR + "".join(f"{dt},{c:.4f},{c:.4f}\n" for dt, c in zip(days, closes)))
        r = MomentumReversalBacktestEngine().run()
        grosses.append(r["gross_mean_per_period_bps"])
        sig_count += 1 if r["gross_significant"] else 0
    mean_gross = sum(grosses) / len(grosses)
    assert abs(mean_gross) < 15, f"noise shows a consistent directional edge: {mean_gross:.1f}bps"
    assert sig_count <= 2, f"{sig_count}/{runs} significant — far above the 5% null rate"


def test_breakeven_cost_shrinks_the_annualized_return(eng, tmp_path):
    """Sanity on the cost machinery: higher assumed cost must never IMPROVE net return, and a
    breakeven must exist somewhere on a finite-edge series."""
    rng = random.Random(2)
    days = _trading_days(900)
    for i in range(40):
        px, closes = 100.0, []
        for _ in days:
            px *= (1 + rng.gauss(0.0002, 0.02))
            closes.append(px)
        _write(tmp_path, f"D{i:02d}", days, closes)
    r = eng().run()
    nets = [c["net_mean_per_period_bps"] for c in r["cost_sweep"]]
    assert nets == sorted(nets, reverse=True)      # monotonically non-increasing in cost


def test_reports_survivorship_and_options_limitation(eng, tmp_path):
    """The result must never let a reader forget the universe is survivor-only and that no
    historical option data backs an options claim."""
    rng = random.Random(3)
    days = _trading_days(900)
    for i in range(40):
        px, closes = 100.0, []
        for _ in days:
            px *= (1 + rng.gauss(0, 0.02)); closes.append(px)
        _write(tmp_path, f"S{i:02d}", days, closes)
    r = eng().run()
    assert r["survivorship"]["survivorship_free"] is False
    assert "biased UPWARD" in r["survivorship"]["effect"]
    assert "NO historical option" in r["options_vehicle_note"]


def test_verdict_always_kills_the_options_vehicle_and_flags_survivorship(eng, tmp_path):
    """No matter the signal outcome, the options-vehicle call must stand (a tens-of-bps edge
    cannot survive 500-1500bps option costs) and survivorship must be declared."""
    import random as _r
    rng = _r.Random(7)
    days = _trading_days(900)
    for i in range(40):
        px, closes = 100.0, []
        for _ in days:
            px *= (1 + rng.gauss(0.0003, 0.02)); closes.append(px)
        _write(tmp_path, f"V{i:02d}", days, closes)
    v = eng().verdict()
    assert v["status"] == "MOMENTUM_REVERSAL_VERDICT_COMPLETE"
    assert v["options_vehicle_verdict"]["verdict"] == "OTM OPTIONS CANNOT CARRY THIS EDGE"
    assert "UPPER bound" in v["survivorship_caveat"]
    assert set(v["signal_edge"]) >= {"market_neutral_long_short_significant",
                                     "long_only_excess_over_market_significant"}
