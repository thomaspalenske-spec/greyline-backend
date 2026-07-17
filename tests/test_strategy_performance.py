import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.strategy_performance_engine import StrategyPerformanceEngine

MOD = "app.services.strategy_performance_engine"


def _trade(symbol, pnl, at="2026-07-16T13:00:00", side="BUY"):
    return {"trade_intent": "MOMENTUM_REVERSAL", "status": "CLOSED", "symbol": symbol,
            "side": side, "realized_pnl": pnl, "exit_timestamp": at,
            "entry_price": 100.0, "exit_price": 100.0 + pnl, "quantity": 1}


def _run(trades):
    fake = MagicMock()
    fake._read_all.return_value = trades
    with patch(f"{MOD}.PaperTradeLedgerEngine", return_value=fake), \
         patch(f"{MOD}.MomentumReversalStrategyEngine") as MockStrat:
        MockStrat.CAPITAL_BASE = 10000.0
        MockStrat.return_value.universe.return_value = ({}, "2026-07-16", "TRADESTATION_LIVE")
        return StrategyPerformanceEngine(capital_base=10000.0).evaluate()


def test_tiny_sample_never_claims_an_edge_even_when_winning():
    # Three big winners would look like a great strategy — it must still refuse to conclude.
    out = _run([_trade("A", 50.0), _trade("B", 40.0), _trade("C", 60.0)])
    assert out["verdict"] == "INSUFFICIENT_SAMPLE"
    assert out["realized_pnl"] == 150.0
    assert out["win_rate_pct"] == 100.0


def test_realized_pnl_and_equity_curve_accumulate():
    out = _run([_trade("A", 10.0, "2026-07-14T10:00:00"),
                _trade("B", -4.0, "2026-07-15T10:00:00"),
                _trade("C", 6.0, "2026-07-16T10:00:00")])
    assert out["realized_pnl"] == 12.0
    assert [p["cumulative"] for p in out["equity_curve"]] == [10.0, 6.0, 12.0]
    assert out["wins"] == 2 and out["losses"] == 1


def test_win_loss_stats():
    out = _run([_trade("A", 10.0), _trade("B", -5.0)])
    assert out["avg_win"] == 10.0
    assert out["avg_loss"] == -5.0
    assert out["profit_factor"] == 2.0


def test_large_positive_sample_reports_emerging_edge():
    trades = [_trade(f"S{i}", 10.0 if i % 4 else -5.0) for i in range(40)]
    out = _run(trades)
    assert out["closed_trades"] == 40
    assert out["verdict"] == "POSITIVE_EDGE_EMERGING"
    assert out["expectancy_t_stat"] > 2


def test_large_noisy_sample_reports_no_detectable_edge():
    # Alternating +/- of equal size -> expectancy ~0, must not claim an edge.
    trades = [_trade(f"S{i}", 10.0 if i % 2 else -10.0) for i in range(40)]
    out = _run(trades)
    assert out["verdict"] == "NO_DETECTABLE_EDGE"


def test_no_trades_is_insufficient_not_an_error():
    out = _run([])
    assert out["verdict"] == "INSUFFICIENT_SAMPLE"
    assert out["closed_trades"] == 0
    assert out["realized_pnl"] == 0
