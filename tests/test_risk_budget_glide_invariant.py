"""Risk-budget glide invariant: the sleeve-target SUM must never over-subscribe the book (the 2026-08-18
111% pre-open break) for ANY glide state. The re-mix group is kept summing to its combined static budget by
a proportional pull-back; sleeves outside the group (momentum/vrp) are untouched. Reads the real historical
CSVs for the advisory vols, so the module is exempt from the app/data wipe. No orders, no network."""

import json

import pytest

from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine as B


@pytest.fixture
def armed(monkeypatch, tmp_path):
    of = tmp_path / "ov.json"
    monkeypatch.setattr(B, "OVERRIDE_FILE", of)
    # trend + vol_carry pinned (as in prod); low_vol + xs_momentum NON-pinned (default) — the exact mix
    # whose glide over-subscribed the book.
    for s, p in (("TREND", "28"), ("VOL_CARRY", "20")):
        monkeypatch.setenv("GREYLINE_%s_ALLOC_PCT" % s, p)
    monkeypatch.setenv("GREYLINE_SLEEVE_RISK_BUDGET", "true")
    return of


def _group_and_target():
    grp = set(B._risk_parity_table().keys())
    return grp, sum(B._static_pct(s) for s in grp)


def test_group_sum_never_exceeds_combined_budget_fresh_arm(armed):
    # fresh arm (no risk_trim yet): non-pinned sleeves snap to full risk-parity, pinned stay at pin — the
    # raw sum overshoots. pct() must pull the GROUP back to its combined budget.
    grp, target = _group_and_target()
    assert sum(B.pct(s) for s in grp) <= target + 0.05


def test_group_sum_invariant_mid_glide(armed):
    armed.write_text(json.dumps({"pct": {}, "risk_trim": {"trend": 24.0, "vol_carry": 16.0}}))
    grp, target = _group_and_target()
    assert sum(B.pct(s) for s in grp) <= target + 0.05


def test_whole_book_never_over_subscribes(armed):
    # the actual bug: total across ALL sleeves stayed <= 100% (was 111%)
    assert sum(B.pct(s) for s in B.DEFAULT_PCT) <= 100.0 + 1e-6


def test_whole_book_invariant_mid_glide(armed):
    armed.write_text(json.dumps({"pct": {}, "risk_trim": {"trend": 24.0, "vol_carry": 16.0}}))
    assert sum(B.pct(s) for s in B.DEFAULT_PCT) <= 100.0 + 1e-6


def test_sleeves_outside_the_group_untouched(armed):
    # momentum is not in the inverse-vol re-mix (single names, no basket vol) — normalization must not scale it
    grp, _ = _group_and_target()
    assert "momentum" not in grp
    assert B.pct("momentum") == B._static_pct("momentum")


def test_gate_off_is_a_no_op(monkeypatch, tmp_path):
    # with the flag off, pct() == the static pins (no normalization, no re-mix) — sum back to the ~97% target
    monkeypatch.setattr(B, "OVERRIDE_FILE", tmp_path / "ov.json")
    monkeypatch.delenv("GREYLINE_SLEEVE_RISK_BUDGET", raising=False)
    for s, p in (("TREND", "28"), ("VOL_CARRY", "20")):
        monkeypatch.setenv("GREYLINE_%s_ALLOC_PCT" % s, p)
    assert B.pct("vol_carry") == 20.0 and B.pct("trend") == 28.0
    assert sum(B.pct(s) for s in B.DEFAULT_PCT) <= 100.0 + 1e-6
