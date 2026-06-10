import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_equity_timeline_engine import (
    PaperEquityTimelineEngine
)


def test_equity_timeline_builds():
    snapshots = [
        {
            "snapshot_timestamp": "2026-01-01",
            "equity": 10000
        },
        {
            "snapshot_timestamp": "2026-01-02",
            "equity": 10500
        }
    ]

    with patch(
        "app.services.paper_equity_timeline_engine.PaperAccountSnapshotRepository"
    ) as MockRepo:

        MockRepo.return_value.get_snapshots.return_value = snapshots

        result = PaperEquityTimelineEngine().build_timeline()

    assert result["snapshot_count"] == 2
    assert result["latest_equity"] == 10500
    assert result["highest_equity"] == 10500
    assert result["status"] == "EQUITY_TIMELINE_READY"


def test_empty_timeline():
    with patch(
        "app.services.paper_equity_timeline_engine.PaperAccountSnapshotRepository"
    ) as MockRepo:

        MockRepo.return_value.get_snapshots.return_value = []

        result = PaperEquityTimelineEngine().build_timeline()

    assert result["snapshot_count"] == 0
    assert result["latest_equity"] == 0
    assert result["highest_equity"] == 0
