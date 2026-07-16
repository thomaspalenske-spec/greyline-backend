import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.momentum_reversal_rebalance_engine import MomentumReversalRebalanceEngine

MOD = "app.services.momentum_reversal_rebalance_engine"
NOW = datetime(2026, 7, 16, 15, 0, 0)


def _eng(tmp_path, universe_return):
    eng = MomentumReversalRebalanceEngine(top_n=3)
    eng.STATE = tmp_path / "state.json"
    eng.strategy.universe = lambda prefer_live=True: universe_return
    return eng


def _open_market(monkeypatch):
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true")
    m = patch(f"{MOD}.MarketHoursEngine")
    mm = m.start()
    mm.return_value.status.return_value = {"is_regular_session": True, "state": "OPEN"}
    return m


# ---- unit: the staleness classifier ----
def test_csv_fallback_is_stale():
    eng = MomentumReversalRebalanceEngine()
    assert eng._staleness("HISTORICAL_CSV", "2026-06-29", NOW)


def test_old_bar_is_stale_even_if_live():
    eng = MomentumReversalRebalanceEngine()
    assert eng._staleness("TRADESTATION_LIVE", "2026-07-01", NOW)  # 15 days old


def test_current_live_data_is_fresh():
    eng = MomentumReversalRebalanceEngine()
    assert eng._staleness("TRADESTATION_LIVE", "2026-07-15", NOW) is None  # yesterday's close


def test_three_day_weekend_is_not_stale():
    eng = MomentumReversalRebalanceEngine()
    # Friday close, trading the following Tuesday -> 4 calendar days, still allowed
    assert eng._staleness("TRADESTATION_LIVE_CACHED", "2026-07-12", datetime(2026, 7, 16)) is None


# ---- integration: the guard blocks trading, even when forced ----
def test_forced_rebalance_still_refuses_stale_data(tmp_path, monkeypatch):
    m = _open_market(monkeypatch)
    try:
        eng = _eng(tmp_path, ({"AAA": [1.0] * 260}, "2026-06-29", "HISTORICAL_CSV"))
        with patch.object(eng.strategy, "select") as sel:
            out = eng.rebalance(force=True)
            assert out["status"] == "REBALANCE_SKIPPED_STALE_DATA"
            assert out["rebalanced"] is False
            # never even got to selection/trading
            sel.assert_not_called()
    finally:
        m.stop()
