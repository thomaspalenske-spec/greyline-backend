"""Inverse-vol risk-budget advisory + gated live application. Default OFF changes nothing; env pins always
win; ON re-mixes only non-pinned measured sleeves within their own combined budget. Hermetic — vols
monkeypatched, no CSV/network."""

from pathlib import Path

import pytest

from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine as E

_VOLS = {"vol_carry": 0.30, "trend": 0.12, "low_vol": 0.09, "xs_momentum": 0.10}   # SVXY the hot one


@pytest.fixture(autouse=True)
def _fixed_vols(monkeypatch):
    monkeypatch.setattr(E, "_sleeve_instruments", classmethod(lambda cls, s: [cls._canon(s)]))
    monkeypatch.setattr(E, "_basket_vol", classmethod(lambda cls, syms: _VOLS.get(syms[0]) if syms else None))
    monkeypatch.setattr(E, "_rp_cache", {"t": 0.0, "table": None})
    # neutralize any operator pins from the environment so the defaults drive the test
    for s in E.DEFAULT_PCT:
        monkeypatch.delenv("GREYLINE_%s_ALLOC_PCT" % s.upper(), raising=False)
    monkeypatch.delenv("GREYLINE_SLEEVE_RISK_BUDGET", raising=False)


def test_default_off_changes_nothing():
    assert E._risk_budget_on() is False
    for s in ("vol_carry", "trend", "low_vol", "xs_momentum"):
        assert E.pct(s) == E._static_pct(s)                 # identical to legacy sizing


def test_advisory_exposes_risk_concentration():
    a = E.risk_budget_advisory()
    assert a["status"] == "RISK_BUDGET_ADVISORY"
    assert a["total_armed_pct"] == pytest.approx(72.0)      # measured sleeves only (disarmed momentum excluded)
    assert round(sum(r["risk_parity_pct"] for r in a["sleeves"].values()), 1) == 72.0
    # SVXY carry: most volatile -> most risk today -> risk-parity CUTS it hard
    assert a["most_risk_concentrated"]["sleeve"] == "vol_carry"
    assert a["sleeves"]["vol_carry"]["risk_parity_pct"] < a["sleeves"]["vol_carry"]["current_pct"]
    # the least-volatile sleeve gets MORE under risk parity
    assert a["sleeves"]["low_vol"]["risk_parity_pct"] > a["sleeves"]["low_vol"]["current_pct"]


def test_env_pin_always_wins(monkeypatch):
    monkeypatch.setenv("GREYLINE_SLEEVE_RISK_BUDGET", "true")
    monkeypatch.setenv("GREYLINE_VOL_CARRY_ALLOC_PCT", "20")
    assert E.pct("vol_carry") == 20.0                       # pin beats the risk-parity re-mix


def test_risk_budget_on_downweights_the_hot_sleeve(monkeypatch):
    monkeypatch.setenv("GREYLINE_SLEEVE_RISK_BUDGET", "true")
    assert E._risk_budget_on() is True
    assert E.pct("vol_carry") < E._static_pct("vol_carry")   # short-vol sleeve sized down to its risk
    assert E.pct("low_vol") > E._static_pct("low_vol")       # low-vol sleeve sized up


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "app/data/historical/SVXY_daily.csv").exists(),
                    reason="real basket history absent")
def test_real_vols_rank_svxy_highest(monkeypatch):
    # drop the vol monkeypatch: compute real basket vols; SVXY (carry) must be the most volatile armed sleeve
    monkeypatch.undo()
    monkeypatch.setattr(E, "_HIST", Path(__file__).resolve().parents[1] / "app" / "data" / "historical")
    monkeypatch.setattr(E, "_rp_cache", {"t": 0.0, "table": None})
    for s in E.DEFAULT_PCT:
        monkeypatch.delenv("GREYLINE_%s_ALLOC_PCT" % s.upper(), raising=False)
    a = E.risk_budget_advisory()
    vols = {s: r["vol_annual_pct"] for s, r in a["sleeves"].items()}
    assert max(vols, key=vols.get) == "vol_carry"           # SVXY is the highest-vol basket
