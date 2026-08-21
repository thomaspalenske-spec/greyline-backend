"""FOMC-cycle shadow: even-week (0,2,4,6) vs odd-week SPY returns; forward-only accrual; cost charged on
re-entry only; court verdict. Deterministic tmp bars/ledger — no network, no orders."""

import json

import pytest

import app.services.fomc_cycle_shadow_engine as fm
from app.services.fomc_cycle_shadow_engine import FomcCycleShadowEngine as F


@pytest.fixture
def wired(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "BARS", tmp_path)
    monkeypatch.setattr(F, "LEDGER", tmp_path / "led.jsonl")
    # a single known FOMC anchor so cycle math is deterministic
    monkeypatch.setattr(F, "FOMC_DATES", ["2026-01-01"])
    return tmp_path


def test_cycle_even_odd_from_days_since_meeting():
    """Weeks are floor(days-since-meeting / 7); even weeks (0,2,4,6...) are the high-return weeks."""
    monkeypatch_dates = ["2026-01-01"]
    F.FOMC_DATES = monkeypatch_dates
    assert F._cycle("2026-01-01") == (0, 0, True)    # meeting day = week 0, even
    assert F._cycle("2026-01-06") == (5, 0, True)    # day 5  -> week 0, even
    assert F._cycle("2026-01-08") == (7, 1, False)   # day 7  -> week 1, odd
    assert F._cycle("2026-01-15") == (14, 2, True)   # day 14 -> week 2, even
    assert F._cycle("2025-12-31") is None            # before the first known meeting


def test_even_net_charges_cost_only_on_reentry():
    """The strategy trades on re-entry (first even day after a non-even day), so the round-trip cost hits there
    once — not on every even-week day it simply keeps holding."""
    rows = [
        {"date": "2026-01-01", "ret": 0.010, "even_week": True},   # re-entry (no prior even) -> cost
        {"date": "2026-01-02", "ret": 0.010, "even_week": True},   # still holding -> no cost
        {"date": "2026-01-08", "ret": 0.050, "even_week": False},  # flat (odd) -> excluded
        {"date": "2026-01-15", "ret": 0.010, "even_week": True},   # re-entry again -> cost
    ]
    net = F._even_net(rows, cost=0.002)
    assert abs(net[0] - (0.010 - 0.002)) < 1e-9    # cost on re-entry
    assert abs(net[1] - 0.010) < 1e-9              # no cost while held
    assert abs(net[2] - (0.010 - 0.002)) < 1e-9    # cost on the next re-entry
    assert len(net) == 3                            # the odd day is not in the series


def test_run_if_due_forward_only(wired):
    (wired / "SPY_daily.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-01-05,100,100,100,100,1\n"
        "2026-01-06,100,100,100,101,1\n"
        "2026-01-07,100,100,100,102,1\n")
    r1 = F().run_if_due()
    assert r1["ran"] and r1["observations_added"] == 1     # first deploy records ONLY the latest obs
    rows = [json.loads(l) for l in (wired / "led.jsonl").read_text().splitlines() if l.strip()]
    assert [r["date"] for r in rows] == ["2026-01-07"]     # the latest, not the whole history
    assert F().run_if_due()["observations_added"] == 0     # nothing newer


def test_report_structure_and_falsification(wired):
    (wired / "SPY_daily.csv").write_text(
        "date,open,high,low,close,volume\n2026-01-05,100,100,100,100,1\n2026-01-06,100,100,100,101,1\n")
    F().run_if_due()
    r = F().report()
    assert r["status"] == "FOMC_CYCLE_SHADOW" and r["instrument"] == "SPY"
    assert "forward_shadow" in r and "forward_falsification" in r and "historical_context" in r
    assert "FORWARD_SHADOW" in r["forward_shadow"]["track"]


def test_disabled_flag_is_a_noop(wired, monkeypatch):
    monkeypatch.setenv("GREYLINE_FOMC_CYCLE_SHADOW", "false")
    assert F().run_if_due() == {"status": "FOMC_CYCLE_SHADOW_DISABLED", "ran": False}
