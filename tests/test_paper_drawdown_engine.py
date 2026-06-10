import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_drawdown_engine import (
    PaperDrawdownEngine
)


def test_drawdown_calculation():
    timeline = {
        "timeline": [
            {"equity": 10000},
            {"equity": 12000},
            {"equity": 9000},
            {"equity": 11000}
        ]
    }

    with patch(
        "app.services.paper_drawdown_engine.PaperEquityTimelineEngine"
    ) as MockTimeline:

        MockTimeline.return_value.build_timeline.return_value = timeline

        result = PaperDrawdownEngine().calculate()

    assert result["peak_equity"] == 12000
    assert result["max_drawdown_pct"] == 25.0
    assert result["status"] == "DRAWDOWN_ANALYSIS_READY"


def test_empty_timeline_drawdown():
    with patch(
        "app.services.paper_drawdown_engine.PaperEquityTimelineEngine"
    ) as MockTimeline:

        MockTimeline.return_value.build_timeline.return_value = {
            "timeline": []
        }

        result = PaperDrawdownEngine().calculate()

    assert result["peak_equity"] == 0
    assert result["max_drawdown_pct"] == 0
