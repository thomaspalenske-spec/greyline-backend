"""Low-vol (BAB) equity shadow: weighted daily-return math, inverse-vol vs equal-weight fallback, report
gating + SPY drawdown benchmark. Controlled data — no network, no broker, temp ledger."""

import json

import pytest

from app.services.low_volatility_shadow_engine import LowVolatilityShadowEngine as L


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    monkeypatch.setattr(L, "STATE", tmp_path)
    monkeypatch.setattr(L, "LEDGER", tmp_path / "l.jsonl")
    monkeypatch.setenv("GREYLINE_LOW_VOL_SHADOW", "true")
    yield


def test_disabled(monkeypatch):
    monkeypatch.setenv("GREYLINE_LOW_VOL_SHADOW", "false")
    assert L().mark()["status"] == "LOWVOL_SHADOW_DISABLED"


def test_books_weighted_daily_return_using_stored_weights(monkeypatch):
    # seed 'yesterday' with weights + closes, then advance one bar and check the weighted return
    L.LEDGER.write_text(json.dumps({
        "date": "2026-08-06", "month": "2026-08", "weights": {"AAA": 0.6, "BBB": 0.4},
        "closes": {"AAA": 100.0, "BBB": 100.0}, "daily_return": None, "rebalanced": True}) + "\n")
    monkeypatch.setattr(L, "_aligned",
                        lambda self: (["AAA", "BBB"], ["2026-08-06", "2026-08-07"],
                                      {"AAA": [100.0, 110.0], "BBB": [100.0, 90.0]}))
    monkeypatch.setattr(L, "_live_weights", lambda self: {"AAA": 0.6, "BBB": 0.4})
    monkeypatch.setattr(L, "VOL_WIN", -1)      # let the 2-bar synthetic series clear the min-data guard
    r = L().mark()
    # 0.6*(+10%) + 0.4*(-10%) = +2%
    assert r["status"] == "LOWVOL_SHADOW_MARKED"
    assert r["daily_return"] == pytest.approx(0.02, abs=1e-9)


def test_equal_weight_fallback_when_live_weights_unavailable(monkeypatch):
    monkeypatch.setattr(L, "_aligned",
                        lambda self: (["AAA", "BBB", "CCC"], ["2026-08-07"],
                                      {"AAA": [100.0], "BBB": [100.0], "CCC": [100.0]}))
    monkeypatch.setattr(L, "_live_weights", lambda self: {})    # stale vols -> engine returns nothing
    w = L()._rebalance_weights(["AAA", "BBB", "CCC"])
    assert w == pytest.approx({"AAA": 1/3, "BBB": 1/3, "CCC": 1/3})   # fully-invested equal weight


def test_no_new_bar_is_idempotent(monkeypatch):
    L.LEDGER.write_text(json.dumps({"date": "2026-08-07", "month": "2026-08", "weights": {"AAA": 1.0},
                                    "closes": {"AAA": 100.0}, "daily_return": 0.0}) + "\n")
    monkeypatch.setattr(L, "_aligned", lambda self: (["AAA"], ["2026-08-07"], {"AAA": [100.0]}))
    # _aligned reports VOL_WIN+2 guard first; shrink so a 1-bar series passes to reach the no-new-bar path
    monkeypatch.setattr(L, "VOL_WIN", -1)
    assert L().mark()["status"] == "LOWVOL_SHADOW_NO_NEW_BAR"


def test_report_gating_and_spy_drawdown_benchmark(monkeypatch):
    assert L().report()["status"] == "LOWVOL_SHADOW_NO_DATA"
    # 12 daily marks: low-vol basket drifts up gently; SPY drops harder mid-series (bigger drawdown)
    dates = [f"2026-07-{d:02d}" for d in range(1, 13)]
    lv = [0.001, 0.001, -0.002, 0.001, 0.002, -0.001, 0.001, 0.001, 0.000, 0.001, 0.001, 0.001]
    L.LEDGER.write_text("\n".join(
        json.dumps({"date": d, "daily_return": r}) for d, r in zip(dates, lv)) + "\n")
    # SPY closes across those dates with a deeper drawdown than the low-vol path
    spy = {}
    px = 100.0
    spy_rets = [0.005, -0.03, -0.02, 0.01, 0.005, -0.01, 0.01, 0.005, 0.0, 0.005, 0.005, 0.005]
    spy["2026-06-30"] = px
    for d, rr in zip(dates, spy_rets):
        px *= (1 + rr); spy[d] = round(px, 4)
    monkeypatch.setattr(L, "_closes", lambda self, sym, _s=spy: dict(_s) if sym == "SPY" else {})
    rep = L().report()
    assert rep["status"] == "LOWVOL_SHADOW_MEASURING"          # 12 >= MIN_DAYS(10)
    assert rep["days_tracked"] == 12
    assert rep["benchmark"] == "SPY" and rep["benchmark_max_drawdown_pct"] is not None
    # the low-vol basket drew down LESS than SPY -> ratio < 1 (thesis holds on this synthetic data)
    assert rep["drawdown_ratio_vs_spy"] is not None and rep["drawdown_ratio_vs_spy"] < 1
