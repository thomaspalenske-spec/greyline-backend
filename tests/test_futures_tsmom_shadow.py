"""Futures TSMOM shadow: zero-capital long/short time-series-momentum on the continuous futures (the real
managed-futures test vs ETF proxies). Long positive-trend, short negative, settle at live quotes, court's
bar. Hermetic — instruments/trailing/prices monkeypatched, no network."""

import json

import pytest

from app.services.futures_tsmom_shadow_engine import FuturesTsmomShadowEngine as F
from app.services.alt_asset_universe_engine import AltAssetUniverseEngine as Alt


@pytest.fixture(autouse=True)
def _force_session_open(monkeypatch):
    # Force the futures/FX tradeability gate OPEN so these open/settle tests are time-independent (they'd
    # otherwise fail on a weekend/holiday). The gate itself is tested in test_shadow_tradeability_gate.
    monkeypatch.setattr("app.services.shadow_tradeability_gate.futures_fx_session_open", lambda: True)


def test_signal_is_long_short_by_trailing_sign(monkeypatch):
    monkeypatch.setattr(F, "_instruments", lambda self: [("ES", "@ES"), ("US", "@US"), ("CL", "@CL")])
    tr = {"ES": 0.20, "US": -0.10, "CL": 0.05}
    monkeypatch.setattr(F, "_trailing_return", lambda self, k: tr[k])
    sides = {l["symbol"]: l["side"] for l in F()._signal()}
    assert sides == {"ES": "BUY", "US": "SELL", "CL": "BUY"}      # long positive-trend, short negative


def test_mark_opens_then_settles_long_and_short(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "STATE", tmp_path)
    monkeypatch.setattr(F, "OPEN", tmp_path / "o.json")
    monkeypatch.setattr(F, "CLOSED", tmp_path / "c.jsonl")
    monkeypatch.setattr(F, "_instruments", lambda self: [("ES", "@ES"), ("US", "@US"), ("CL", "@CL"), ("GC", "@GC"), ("NQ", "@NQ")])
    tr = {"ES": 0.2, "US": -0.1, "CL": 0.05, "GC": 0.1, "NQ": -0.2}
    monkeypatch.setattr(F, "_trailing_return", lambda self, k: tr[k])
    monkeypatch.setattr(F, "_live_prices", lambda self, syms: {s: 100.0 for s in syms})

    r1 = F().mark()
    assert r1["cohort_opened"] and r1["open_cohorts"] == 1
    assert not F().mark()["cohort_opened"]                        # non-overlapping

    o = json.loads((tmp_path / "o.json").read_text())
    o[0]["opened"] = "2020-01-01"
    (tmp_path / "o.json").write_text(json.dumps(o))
    monkeypatch.setattr(F, "_live_prices", lambda self, syms: {s: 110.0 for s in syms})   # everything +10%
    r3 = F().mark()
    assert r3["cohorts_closed"] == 1
    rec = json.loads((tmp_path / "c.jsonl").read_text().splitlines()[0])
    # 3 longs (ES/CL/GC) gross +0.10; 2 shorts (US/NQ) gross 100/110-1 = -0.0909 -> mean ~ +0.0236
    assert rec["n_long"] == 3 and rec["n_legs"] == 5
    assert abs(rec["gross_return"] - 0.023636) < 1e-3 and rec["net_return"] < rec["gross_return"]


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_FUTURES_TSMOM_SHADOW", "false")
    assert F().mark()["status"] == "FUT_TSMOM_SHADOW_DISABLED"


def test_report_accumulating_on_court_bar(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "OPEN", tmp_path / "o.json")
    monkeypatch.setattr(F, "CLOSED", tmp_path / "c.jsonl")
    monkeypatch.setattr(F, "_instruments", lambda self: [])
    monkeypatch.setattr(F, "_live_prices", lambda self, s: {})
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps({"net_return": 0.01}) for _ in range(3)) + "\n")
    rep = F().report()
    assert rep["cohorts_closed"] == 3 and "accumulating" in rep["verdict"].lower()
    assert rep["rigorous_verdict"]["verdict"].startswith("ACCUMULATING")


def test_alt_refresh_gates_once_per_day(tmp_path, monkeypatch):
    monkeypatch.setattr(Alt, "ALT_STORE", tmp_path)
    monkeypatch.setattr(Alt, "REFRESH_MARK", tmp_path / ".last_refresh")
    calls = {"n": 0}
    monkeypatch.setattr(Alt, "refresh",
                        classmethod(lambda cls, recent_bars=15: (calls.__setitem__("n", calls["n"] + 1) or {"status": "ALT_REFRESH_DONE"})))
    Alt.refresh_if_due()
    r2 = Alt.refresh_if_due()
    assert calls["n"] == 1 and r2["status"] == "ALT_REFRESH_NOT_DUE"   # at most once/UTC day
