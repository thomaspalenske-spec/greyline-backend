import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_performance_summary_engine import PaperPerformanceSummaryEngine


def test_performance_summary_calculates_return_and_drawdown():
    with patch("app.services.paper_performance_summary_engine.PaperEquityTimelineEngine") as MockTimeline:
        with patch("app.services.paper_performance_summary_engine.PaperDrawdownEngine") as MockDrawdown:
            MockTimeline.return_value.build_timeline.return_value = {
                "timeline": [
                    {"equity": 10000},
                    {"equity": 11000}
                ],
                "latest_equity": 11000,
                "highest_equity": 11000,
                "snapshot_count": 2
            }

            MockDrawdown.return_value.calculate.return_value = {
                "max_drawdown_pct": 5.0
            }

            result = PaperPerformanceSummaryEngine().summarize()

    assert result["starting_equity"] == 10000
    assert result["latest_equity"] == 11000
    assert result["highest_equity"] == 11000
    assert result["total_return_pct"] == 10.0
    assert result["max_drawdown_pct"] == 5.0
    assert result["snapshot_count"] == 2


def test_performance_summary_handles_empty_timeline():
    with patch("app.services.paper_performance_summary_engine.PaperEquityTimelineEngine") as MockTimeline:
        with patch("app.services.paper_performance_summary_engine.PaperDrawdownEngine") as MockDrawdown:
            MockTimeline.return_value.build_timeline.return_value = {
                "timeline": [],
                "latest_equity": 0,
                "highest_equity": 0,
                "snapshot_count": 0
            }

            MockDrawdown.return_value.calculate.return_value = {
                "max_drawdown_pct": 0
            }

            result = PaperPerformanceSummaryEngine().summarize()

    assert result["starting_equity"] == 0
    assert result["latest_equity"] == 0
    assert result["total_return_pct"] == 0
    assert result["status"] == "PERFORMANCE_SUMMARY_READY"
