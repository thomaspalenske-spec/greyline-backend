"""FX trend shadow: zero-capital long/short 3-month trend on the 6 spot-FX pairs (completes the alt-asset
measurement trio). Hermetic — instruments/trailing/prices monkeypatched, no network."""

import json

import pytest

from app.services.fx_trend_shadow_engine import FxTrendShadowEngine as F


@pytest.fixture(autouse=True)
def _force_session_open(monkeypatch):
    # Force the futures/FX tradeability gate OPEN so these open/settle tests are time-independent (they'd
    # otherwise fail on a weekend/holiday). The gate itself is tested in test_shadow_tradeability_gate.
    monkeypatch.setattr("app.services.shadow_tradeability_gate.futures_fx_session_open", lambda: True)


def test_signal_long_short_by_trend(monkeypatch):
    monkeypatch.setattr(F, "_instruments", lambda self: [("EURUSD", "EURUSD"), ("USDJPY", "USDJPY"), ("GBPUSD", "GBPUSD")])
    tr = {"EURUSD": 0.03, "USDJPY": -0.02, "GBPUSD": 0.01}
    monkeypatch.setattr(F, "_trailing_return", lambda self, k: tr[k])
    sides = {l["symbol"]: l["side"] for l in F()._signal()}
    assert sides == {"EURUSD": "BUY", "USDJPY": "SELL", "GBPUSD": "BUY"}


def test_mark_opens_then_settles(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "STATE", tmp_path)
    monkeypatch.setattr(F, "OPEN", tmp_path / "o.json")
    monkeypatch.setattr(F, "CLOSED", tmp_path / "c.jsonl")
    monkeypatch.setattr(F, "_instruments", lambda self: [("EURUSD", "EURUSD"), ("USDJPY", "USDJPY"), ("GBPUSD", "GBPUSD"), ("AUDUSD", "AUDUSD")])
    tr = {"EURUSD": 0.03, "USDJPY": -0.02, "GBPUSD": 0.01, "AUDUSD": -0.01}
    monkeypatch.setattr(F, "_trailing_return", lambda self, k: tr[k])
    monkeypatch.setattr(F, "_live_prices", lambda self, syms: {s: 1.0 for s in syms})
    r1 = F().mark()
    assert r1["cohort_opened"] and r1["open_cohorts"] == 1
    assert not F().mark()["cohort_opened"]                        # non-overlapping

    o = json.loads((tmp_path / "o.json").read_text())
    o[0]["opened"] = "2020-01-01"
    (tmp_path / "o.json").write_text(json.dumps(o))
    monkeypatch.setattr(F, "_live_prices", lambda self, syms: {s: 1.1 for s in syms})   # +10%
    r3 = F().mark()
    assert r3["cohorts_closed"] == 1
    rec = json.loads((tmp_path / "c.jsonl").read_text().splitlines()[0])
    # 2 longs +0.10, 2 shorts 1.0/1.1-1 = -0.0909 -> mean ~ +0.00455
    assert rec["n_long"] == 2 and abs(rec["gross_return"] - 0.004545) < 1e-3


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_FX_TREND_SHADOW", "false")
    assert F().mark()["status"] == "FX_TREND_SHADOW_DISABLED"


def test_report_accumulating_on_court_bar(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "OPEN", tmp_path / "o.json")
    monkeypatch.setattr(F, "CLOSED", tmp_path / "c.jsonl")
    monkeypatch.setattr(F, "_instruments", lambda self: [])
    monkeypatch.setattr(F, "_live_prices", lambda self, s: {})
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps({"net_return": 0.005}) for _ in range(3)) + "\n")
    rep = F().report()
    assert rep["cohorts_closed"] == 3 and "accumulating" in rep["verdict"].lower()
    assert rep["rigorous_verdict"]["verdict"].startswith("ACCUMULATING")
