"""The mechanical-flow study must report NOTHING on data that contains nothing.

A research engine that finds edge in pure noise is worse than no research engine: it
launders randomness into confidence. These tests feed it known-null data and demand silence.
"""

import random

import pytest

from app.services.mechanical_flow_research_engine import MechanicalFlowResearchEngine

HDR = "date,open,high,low,close,volume\n"


def _trading_days(n, start_year=2000):
    """Weekday-only date strings — enough structure for month/expiry labelling."""
    from datetime import date, timedelta
    out, d = [], date(start_year, 1, 3)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


@pytest.fixture
def noise_engine(tmp_path, monkeypatch):
    """A universe of pure random walks: by construction there is NO effect to find."""
    monkeypatch.setattr(MechanicalFlowResearchEngine, "HIST_DIR", tmp_path)
    monkeypatch.setattr(MechanicalFlowResearchEngine, "OUT", tmp_path / "study.json")
    monkeypatch.setattr(MechanicalFlowResearchEngine, "PERMUTATIONS", 400)  # keep tests fast
    rng = random.Random(7)
    days = _trading_days(1600)
    for i in range(60):
        px, rows = 100.0, []
        for d in days:
            px *= (1 + rng.gauss(0, 0.015))
            rows.append(f"{d},{px:.4f},{px:.4f},{px:.4f},{px:.4f},5000000\n")
        (tmp_path / f"SYM{i:02d}_daily.csv").write_text(HDR + "".join(rows))
    eng = MechanicalFlowResearchEngine()
    monkeypatch.setattr(eng, "_load", lambda exclude_stubs=True: (
        {p.name.replace("_daily.csv", ""): [
            (l.split(",")[0], float(l.split(",")[4]))
            for l in p.read_text().splitlines()[1:] if l.strip()]
         for p in sorted(tmp_path.glob("*_daily.csv"))}, {}))
    return eng


def test_finds_no_edge_in_pure_noise(noise_engine):
    """The headline guarantee: random walks must yield an empty surviving set."""
    r = noise_engine.run(save=False)
    assert r["verdict"] == "NO_MECHANICAL_FLOW_EDGE_DETECTED"
    assert r["surviving_correction"] == []


def test_rebalance_ranking_never_overlaps_its_measurement_window(noise_engine):
    """THE regression guard.

    The first implementation ranked on the return THROUGH the month-end date while the
    measurement window also STARTED on it. A stock was labelled a winner because of a day
    that was then counted in its result — pure double-counting. It reported -149.72bps at
    p=0.0001; ranking one bar earlier collapsed it to -13.98bps at p=0.40.

    On noise, a look-ahead leak shows up as an implausibly large |spread| and a hit rate far
    from 0.5. Both must stay near their null values.
    """
    r = noise_engine.run(save=False)
    h2 = next(x for x in r["results"] if x["hypothesis"].startswith("H2"))
    assert h2.get("months", 0) >= 40
    assert abs(h2["mean_spread_bps"]) < 60, (
        f"spread {h2['mean_spread_bps']}bps on RANDOM data implies look-ahead leakage")
    assert 0.35 < h2["hit_rate"] < 0.65
    assert h2["significant_after_correction"] is False


def test_every_p_value_is_corrected_for_the_prereg_count(noise_engine):
    """Three pre-registered hypotheses -> every p must be Bonferroni-scaled by three.
    Uncorrected p-values over a multi-hypothesis study is how the last flow edge was faked."""
    r = noise_engine.run(save=False)
    assert r["hypotheses_pre_registered"] == 3
    for x in r["results"]:
        if "p_value" in x:
            # tolerance covers rounding only: the engine scales the UNROUNDED p and rounds
            # after, which is more correct than scaling the already-rounded value
            assert x["p_value_bonferroni"] == pytest.approx(min(1.0, x["p_value"] * 3), abs=1e-3)
            assert x["p_value_bonferroni"] >= x["p_value"] - 1e-9


def test_dates_not_symbol_days_are_the_unit_of_observation(noise_engine):
    """60 symbols x 1600 days is NOT 96,000 observations — same-day returns are one bet.
    Counting symbol-days is how 3.4M rows manufacture significance out of noise."""
    r = noise_engine.run(save=False)
    h1 = next(x for x in r["results"] if x["hypothesis"].startswith("H1"))
    assert "date" in h1["unit_of_observation"]
    assert h1["event_n"] + h1["control_n"] <= r["trading_dates"]
