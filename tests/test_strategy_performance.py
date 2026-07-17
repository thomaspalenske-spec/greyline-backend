import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.strategy_performance_engine import StrategyPerformanceEngine

MOD = "app.services.strategy_performance_engine"


def _trade(symbol, pnl, at="2026-07-16T13:00:00", side="BUY", entry=100.0, qty=1):
    return {"trade_intent": "MOMENTUM_REVERSAL", "status": "CLOSED", "symbol": symbol,
            "side": side, "realized_pnl": pnl, "exit_timestamp": at,
            "entry_price": entry, "exit_price": entry + pnl, "quantity": qty}


def _run(trades, cost_bps=0.0):
    fake = MagicMock()
    fake._read_all.return_value = trades
    with patch(f"{MOD}.PaperTradeLedgerEngine", return_value=fake), \
         patch(f"{MOD}.MomentumReversalStrategyEngine") as MockStrat:
        MockStrat.CAPITAL_BASE = 10000.0
        MockStrat.COST_BPS_ROUND_TRIP = cost_bps
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


# ---- transaction costs: the verdict must be net, not frictionless ----

def test_costs_are_charged_against_realized_pnl():
    # $10,000 notional, 10bps round trip = $10 cost against a $30 gross win.
    out = _run([_trade("A", 30.0, entry=100.0, qty=100)], cost_bps=10)
    assert out["realized_pnl_gross"] == 30.0
    assert out["transaction_costs"] == 10.0
    assert out["realized_pnl"] == 20.0        # net is the headline
    assert out["cost_bps_round_trip"] == 10


def test_costs_can_flip_a_marginal_edge_to_no_edge():
    # A thin gross edge that looks significant frictionless...
    trades = [_trade(f"S{i}", 12.0 if i % 4 else -6.0, entry=100.0, qty=100) for i in range(40)]
    gross = _run(trades, cost_bps=0)
    assert gross["verdict"] == "POSITIVE_EDGE_EMERGING"

    # ...is eaten once a realistic round trip is charged. This is the whole point:
    # a frictionless verdict would have said "ship it".
    net = _run(trades, cost_bps=10)
    assert net["realized_pnl"] < gross["realized_pnl"]
    assert net["verdict"] != "POSITIVE_EDGE_EMERGING"


def test_expectancy_and_curve_are_net_of_cost():
    out = _run([_trade("A", 30.0, entry=100.0, qty=100)], cost_bps=10)
    assert out["expectancy_per_trade"] == 20.0          # not 30
    assert out["equity_curve"][0]["cumulative"] == 20.0
