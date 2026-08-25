"""Dispersion / correlation-premium shadow: implied corr (index IV vs basket IV) at entry minus realized corr
over a monthly hold, cost-net, judged on the court's bar. Hermetic — IVs/bars/RTH monkeypatched, no network."""

import json

import pytest

import app.services.dispersion_shadow_engine as dm
from app.services.dispersion_shadow_engine import DispersionShadowEngine as D


@pytest.fixture(autouse=True)
def _session_open(monkeypatch):
    monkeypatch.setattr("app.services.shadow_tradeability_gate.equity_session_open", lambda: True)


def test_proxy_correlation_formula():
    # index vol 0.10, components avg 0.20 -> (0.10/0.20)^2 = 0.25
    assert D._corr(0.10, [0.20, 0.20]) == 0.25
    assert D._corr(0.15, [0.30, 0.30, 0.30]) == 0.25
    assert D._corr(None, [0.2]) is None and D._corr(0.1, []) is None


def test_mark_opens_then_settles_premium(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLINE_DISPERSION_COST", "0.02")
    monkeypatch.setattr(dm, "STATE", tmp_path)
    monkeypatch.setattr(D, "OPEN", tmp_path / "o.json")
    monkeypatch.setattr(D, "CLOSED", tmp_path / "c.jsonl")
    monkeypatch.setattr(D, "BASKET", ["A", "B", "C", "D"])
    # entry: index IV 0.10, comps 0.20 each -> implied corr (0.10/0.20)^2 = 0.25
    monkeypatch.setattr(D, "_ivs", lambda self, syms: {"SPY": 0.10, "A": 0.20, "B": 0.20, "C": 0.20, "D": 0.20})
    r1 = D().mark()
    assert r1["cohort_opened"] and r1["open_cohorts"] == 1
    o = json.loads((tmp_path / "o.json").read_text())
    assert o[0]["implied_corr"] == 0.25

    # age past the hold, then settle: realized index vol 0.05, comps 0.20 -> realized corr (0.05/0.20)^2 = 0.0625
    o[0]["opened"] = "2020-01-01"
    (tmp_path / "o.json").write_text(json.dumps(o))
    monkeypatch.setattr(D, "_realized_vol",
                        lambda self, sym, s, e: 0.05 if sym == "SPY" else 0.20)
    r3 = D().mark()
    assert r3["cohorts_closed"] == 1
    rec = json.loads((tmp_path / "c.jsonl").read_text().splitlines()[0])
    assert rec["implied_corr"] == 0.25 and rec["realized_corr"] == 0.0625
    assert rec["dispersion_premium"] == round(0.25 - 0.0625, 6)          # +0.1875 correlation premium
    assert rec["net_return"] == round(0.1875 - 0.02, 6)                  # cost-net on BOTH the premium


def test_realized_vol_from_bars(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "BARS", tmp_path)
    (tmp_path / "ZZ_daily.csv").write_text(
        "date,open,high,low,close,volume\n" +
        "".join(f"2026-01-{i:02d},1,1,1,{100+(i%2)},1\n" for i in range(1, 12)))  # oscillating -> positive vol
    rv = D._realized_vol("ZZ", "2026-01-01", "2026-01-31")
    assert rv is not None and rv > 0


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_DISPERSION_SHADOW", "false")
    assert D().mark()["status"] == "DISPERSION_SHADOW_DISABLED"
