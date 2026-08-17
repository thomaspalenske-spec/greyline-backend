"""Risk-budget sizing backtest: metric correctness, the long-history proxy substitution (so the crash
years are actually in-window), and the de-concentration direction. Uses the real historical CSVs (read-only,
no network, no orders)."""

import math

import pytest

from app.services.risk_budget_sizing_backtest_engine import RiskBudgetSizingBacktestEngine as B


@pytest.fixture
def armed_sleeves(monkeypatch):
    """Pin the four armed sleeves so the risk-budget advisory (which the backtest reads its weights from)
    has a populated sleeve set — the conftest arming-flag strip otherwise leaves it empty."""
    for s, pct in (("TREND", "28"), ("VOL_CARRY", "20"), ("LOW_VOL", "12"), ("XS_MOMENTUM", "12")):
        monkeypatch.setenv("GREYLINE_%s_ALLOC_PCT" % s, pct)


# ---- pure metric helper ----

def test_metrics_flat_series_zero_drawdown():
    m = B._metrics([0.0] * 100)
    assert m["ann_return_pct"] == 0.0
    assert m["max_drawdown_pct"] == 0.0
    assert m["ann_vol_pct"] == 0.0

def test_metrics_drawdown_and_worst_day():
    # one -10% day inside otherwise-flat series -> max_dd == -10%, worst_day == -10%
    rets = [0.0] * 50 + [-0.10] + [0.0] * 50
    m = B._metrics(rets)
    assert m["worst_day_pct"] == -10.0
    assert m["max_drawdown_pct"] == -10.0

def test_metrics_none_when_too_short():
    assert B._metrics([0.01] * 10) is None

def test_metrics_annualized_vol_scales_sqrt_252():
    # constant-magnitude alternating returns -> known daily std, annualized by sqrt(252)
    rets = [0.01, -0.01] * 200
    m = B._metrics(rets)
    daily_std = 0.01                     # population-ish; sample std ~0.01
    assert abs(m["ann_vol_pct"] - daily_std * math.sqrt(252) * 100) < 3.0


# ---- proxy substitution: the crash years must be in-window ----

def test_history_proxy_maps_young_share_classes():
    assert B._HISTORY_PROXY.get("QQQM") == "QQQ"
    assert B._HISTORY_PROXY.get("GLDM") == "GLD"

def test_backtest_window_reaches_the_crash_years(armed_sleeves):
    r = B.run()
    assert r.get("status") == "RISK_BUDGET_SIZING_BACKTEST"
    assert "error" not in r, r.get("error")
    start = r["window"]["start"]
    # without the QQQM->QQQ proxy this starts 2020-10 and misses both short-vol crashes; with it, <= 2014
    assert start <= "2014-01-01", f"window starts {start} — crash years (2018/2020) not covered"
    assert r["window"]["days"] > 2000


# ---- de-concentration direction ----

def test_risk_parity_lowers_vol_and_underweights_short_vol(armed_sleeves):
    r = B.run()
    # the risk-parity mix must carry LESS total vol than the current mix (that's the whole point)
    assert r["risk_parity"]["ann_vol_pct"] < r["current"]["ann_vol_pct"]
    # and it must UNDER-weight the highest-vol sleeve (vol_carry) relative to the current mix
    vc = next((s for s in r["sleeves"] if s["sleeve"] == "vol_carry"), None)
    assert vc is not None
    assert vc["risk_parity_weight_pct"] < vc["current_weight_pct"]

def test_weights_normalize_to_100(armed_sleeves):
    r = B.run()
    assert abs(sum(s["current_weight_pct"] for s in r["sleeves"]) - 100.0) < 0.5
    assert abs(sum(s["risk_parity_weight_pct"] for s in r["sleeves"]) - 100.0) < 0.5
