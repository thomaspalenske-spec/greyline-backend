"""PEAD engine must find the effect when it's planted and NOTHING when it isn't. If it can't
tell those apart, no number it reports on real earnings data means anything."""

import json
import random

import pytest

from app.services.pead_research_engine import PEADResearchEngine


def _days(n, y=2005):
    from datetime import date, timedelta
    out, d = [], date(y, 1, 3)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


@pytest.fixture
def eng(tmp_path, monkeypatch):
    monkeypatch.setattr(PEADResearchEngine, "TR_DIR", tmp_path / "tr")
    monkeypatch.setattr(PEADResearchEngine, "EARN_DIR", tmp_path / "earn")
    monkeypatch.setattr(PEADResearchEngine, "OUT", tmp_path / "out.json")
    (tmp_path / "tr").mkdir(); (tmp_path / "earn").mkdir()
    monkeypatch.setattr(PEADResearchEngine, "PERMUTATIONS", 600)
    return PEADResearchEngine(), tmp_path


def _build(tmp_path, days, drift_by_surprise, seed=0, n_sym=60):
    """Write price + earnings files. drift_by_surprise scales post-event drift by surprise."""
    rng = random.Random(seed)
    for i in range(n_sym):
        sym = f"S{i:03d}"
        # quarterly events with a random surprise
        evs, px, closes = [], 100.0, []
        surprise_at = {}
        for j, d in enumerate(days):
            if j % 63 == 0 and j > 0:
                sp = rng.uniform(-30, 30)
                evs.append({"report_date": d, "surprise_percentage": sp})
                surprise_at[j] = sp
            closes.append(px)
            # base random walk
            step = rng.gauss(0, 0.012)
            # planted drift: for DRIFT_WINDOW days after an event, add surprise-scaled drift
            for j0, sp in list(surprise_at.items()):
                if 0 < j - j0 <= 40:
                    step += drift_by_surprise * (sp / 100.0) / 40.0
            px *= (1 + step)
        (tmp_path / "tr" / f"{sym}_total_return.csv").write_text(
            "date,close,adj_close\n" + "".join(f"{d},{c:.4f},{c:.4f}\n" for d, c in zip(days, closes)))
        (tmp_path / "earn" / f"{sym}.json").write_text(json.dumps(evs))


def test_finds_no_pead_when_none_exists(eng):
    """Pure random walks with random surprises -> no relationship. Must report NO edge."""
    e, tmp = eng
    _build(tmp, _days(1400), drift_by_surprise=0.0, seed=1)
    r = e.run(save=False)
    assert r["status"] == "PEAD_STUDY_COMPLETE"
    assert r["verdict"] == "NO_PEAD_EDGE_DETECTED", f"found fake PEAD: {r['primary']}"


def test_detects_pead_when_planted(eng):
    """A real surprise-scaled drift must be found — otherwise the engine is blind and a null
    on real data would be meaningless."""
    e, tmp = eng
    _build(tmp, _days(1400), drift_by_surprise=0.60, seed=2)
    r = e.run(save=False)
    p = r["primary"]
    assert p.get("significant_after_correction") is True, f"missed a planted effect: {p}"
    assert p["mean_spread_pct"] > 0


def test_entry_is_after_the_announcement_so_the_jump_is_not_counted(eng):
    """The announcement gap is not capturable. Entry must be lagged past it."""
    e, tmp = eng
    assert e.ENTRY_LAG_DAYS >= 1
    _build(tmp, _days(1400), drift_by_surprise=0.0, seed=3)
    r = e.run(save=False)
    assert "forfeited" in r["design"]["entry"]


def test_reports_cohorts_not_events_as_the_unit(eng):
    """Earnings cluster in seasons — treating each event as independent inflates n ~100x."""
    e, tmp = eng
    _build(tmp, _days(1400), drift_by_surprise=0.0, seed=4)
    r = e.run(save=False)
    p = r["primary"]
    assert p["cohorts"] < p["events"], "inference unit must be the cohort, not the event"
    assert "cohort" in r["design"]["unit_of_inference"]
