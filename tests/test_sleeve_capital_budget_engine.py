"""Unit tests for the %-of-equity sleeve budget resolver. No broker calls, no orders."""

import os

import pytest

from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine as B


@pytest.fixture(autouse=True)
def _clear_cache():
    B._cache = {"t": 0.0, "equity": None, "cash": None}
    yield
    B._cache = {"t": 0.0, "equity": None, "cash": None}


def _stub_live(monkeypatch, equity, cash):
    monkeypatch.setattr(B, "_read_equity", classmethod(lambda cls: equity))
    monkeypatch.setattr(B, "_read_deployable_cash", classmethod(lambda cls, eq: cash))


def test_default_pcts_sum_to_100():
    assert B.total_pct() == pytest.approx(100.0)


def test_budget_is_pct_of_equity(monkeypatch):
    _stub_live(monkeypatch, equity=20000.0, cash=20000.0)     # cash not binding
    assert B.budget_usd("trend") == pytest.approx(0.28 * 20000.0)      # 5600
    assert B.budget_usd("momentum") == pytest.approx(0.25 * 20000.0)   # 5000
    assert B.budget_usd("vol_carry") == pytest.approx(0.20 * 20000.0)  # 4000


def test_scales_with_equity(monkeypatch):
    # Same sleeve, bigger account -> bigger budget (the whole point of %-of-equity).
    _stub_live(monkeypatch, equity=10000.0, cash=10000.0)
    small = B.budget_usd("momentum")
    B._cache = {"t": 0.0, "equity": None, "cash": None}
    _stub_live(monkeypatch, equity=15000.0, cash=15000.0)
    big = B.budget_usd("momentum")
    assert big > small
    assert big == pytest.approx(1.5 * small)


def test_carry_alias(monkeypatch):
    _stub_live(monkeypatch, equity=10000.0, cash=10000.0)
    assert B.budget_usd("carry") == B.budget_usd("vol_carry")


def test_cash_clamp_binds(monkeypatch):
    # Only $1,000 deployable -> a share-buying sleeve can't target more than the cash on hand.
    _stub_live(monkeypatch, equity=10000.0, cash=1000.0)
    assert B.budget_usd("trend", clamp_to_cash=True) == pytest.approx(1000.0)   # 2800 target clamped
    assert B.budget_usd("trend", clamp_to_cash=False) == pytest.approx(2800.0)  # risk-caps opt out


def test_env_override_pct(monkeypatch):
    monkeypatch.setenv("GREYLINE_MOMENTUM_ALLOC_PCT", "40")
    _stub_live(monkeypatch, equity=10000.0, cash=10000.0)
    assert B.pct("momentum") == pytest.approx(40.0)
    assert B.budget_usd("momentum") == pytest.approx(4000.0)


def test_bad_pct_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("GREYLINE_TREND_ALLOC_PCT", "not-a-number")
    assert B.pct("trend") == pytest.approx(28.0)


def test_pct_clamped_to_0_100(monkeypatch):
    monkeypatch.setenv("GREYLINE_VRP_ALLOC_PCT", "250")
    assert B.pct("vrp") == pytest.approx(100.0)
    monkeypatch.setenv("GREYLINE_VRP_ALLOC_PCT", "-5")
    assert B.pct("vrp") == pytest.approx(0.0)


def test_zero_cash_gives_zero_budget_for_share_sleeves(monkeypatch):
    _stub_live(monkeypatch, equity=10000.0, cash=0.0)
    assert B.budget_usd("momentum", clamp_to_cash=True) == pytest.approx(0.0)


def test_equity_read_failure_uses_static_fallback(monkeypatch):
    # Equity unreadable AND base unreadable -> explicit per-sleeve fallback dollars, never a guess.
    monkeypatch.setattr(B, "_read_equity", classmethod(lambda cls: None))
    monkeypatch.setattr(B, "_base", classmethod(lambda cls: None))
    monkeypatch.setattr(B, "_read_deployable_cash", classmethod(lambda cls, eq: None))
    assert B.budget_usd("momentum") == pytest.approx(B._FALLBACK_USD["momentum"])
    assert B.budget_usd("trend") == pytest.approx(B._FALLBACK_USD["trend"])


def test_snapshot_shape(monkeypatch):
    _stub_live(monkeypatch, equity=12000.0, cash=9000.0)
    snap = B.snapshot()
    assert snap["mission_equity"] == 12000.0
    assert snap["deployable_cash"] == 9000.0
    assert snap["deployable_100pct"] is True
    assert set(snap["sleeves"]) == set(B.DEFAULT_PCT)
    for s, row in snap["sleeves"].items():
        assert row["budget_usd"] >= 0
