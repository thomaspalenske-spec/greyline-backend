import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_performance_summary_engine import PaperPerformanceSummaryEngine

MODULE = "app.services.paper_performance_summary_engine"


def _summarize(trades, max_drawdown_pct=0.0):
    # The engine derives equity from ledger trade PnL (starting equity 10000),
    # and drawdown from PaperDrawdownEngine. Mock both for a deterministic test.
    with patch(f"{MODULE}.PaperTradeLedgerEngine") as MockLedger, \
         patch(f"{MODULE}.PaperDrawdownEngine") as MockDrawdown:
        MockLedger.return_value.history.return_value = {"trades": trades}
        MockDrawdown.return_value.calculate.return_value = {"max_drawdown_pct": max_drawdown_pct}
        return PaperPerformanceSummaryEngine().summarize()


def test_performance_summary_calculates_return_and_drawdown():
    # One closed trade of +1000 realized PnL -> equity 10000 -> 11000 (+10%).
    result = _summarize(
        [{"status": "CLOSED", "symbol": "NVDA", "realized_pnl": 1000}],
        max_drawdown_pct=5.0,
    )

    assert result["starting_equity"] == 10000.0
    assert result["latest_equity"] == 11000.0
    assert result["highest_equity"] == 11000.0
    assert result["total_return_pct"] == 10.0
    assert result["max_drawdown_pct"] == 5.0
    assert result["closed_trade_count"] == 1
    assert result["win_count"] == 1


def test_performance_summary_handles_empty_ledger():
    result = _summarize([], max_drawdown_pct=0)

    assert result["starting_equity"] == 10000.0
    assert result["latest_equity"] == 10000.0
    assert result["total_return_pct"] == 0.0
    assert result["paper_trade_count"] == 0
    assert result["status"] == "PERFORMANCE_SUMMARY_READY"
