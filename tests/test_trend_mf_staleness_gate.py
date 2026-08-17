"""Root C: trend + managed-futures must REFUSE to trade on stale CSV bars (decision-time gate).

Pure signal-logic tests — no orders, no network. CSV history is written to a tmp dir.
"""

from datetime import date, timedelta

from app.services.trend_following_engine import TrendFollowingEngine
from app.services.managed_futures_engine import ManagedFuturesEngine


def _write_csv(path, n_bars, last_day):
    rows = ["date,close"]
    for i in range(n_bars):
        d = last_day - timedelta(days=(n_bars - 1 - i))
        rows.append(f"{d.isoformat()},{100 + i * 0.1:.2f}")
    path.write_text("\n".join(rows) + "\n")


def _prep(eng, tmp_path, n_bars, last_day):
    eng.HIST = tmp_path
    _write_csv(tmp_path / "SPY_daily.csv", n_bars, last_day)


def test_trend_flags_stale_bars(tmp_path):
    eng = TrendFollowingEngine()
    _prep(eng, tmp_path, eng.SMA + 5, date.today() - timedelta(days=10))   # newest bar 10 days old
    sig = eng._signal("SPY", live_last=123.0)
    assert sig is not None and sig.get("stale")                           # refuses — stale


def test_trend_trades_fresh_bars(tmp_path):
    eng = TrendFollowingEngine()
    _prep(eng, tmp_path, eng.SMA + 5, date.today())                       # newest bar today
    sig = eng._signal("SPY", live_last=123.0)
    assert sig is not None and "stale" not in sig and "uptrend" in sig    # real signal


def test_managed_futures_flags_stale_bars(tmp_path):
    eng = ManagedFuturesEngine()
    n = max(eng.LOOKBACKS) + 5
    _prep(eng, tmp_path, n, date.today() - timedelta(days=10))
    sig = eng._signal("SPY", live_last=123.0)
    assert sig is not None and sig.get("stale")


def test_managed_futures_trades_fresh_bars(tmp_path):
    eng = ManagedFuturesEngine()
    n = max(eng.LOOKBACKS) + 5
    _prep(eng, tmp_path, n, date.today())
    sig = eng._signal("SPY", live_last=123.0)
    assert sig is not None and "stale" not in sig and "blend" in sig
