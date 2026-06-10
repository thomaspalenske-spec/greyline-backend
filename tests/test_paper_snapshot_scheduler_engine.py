import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_snapshot_scheduler_engine import (
    PaperSnapshotSchedulerEngine
)


def test_scheduler_cycle():
    with patch(
        "app.services.paper_snapshot_scheduler_engine.PaperSnapshotCaptureEngine"
    ) as MockCapture:

        MockCapture.return_value.capture.return_value = {
            "snapshot_saved": True
        }

        result = (
            PaperSnapshotSchedulerEngine()
            .run_cycle(
                cash_balance=10000,
                positions=[]
            )
        )

    assert result["cycle_completed"] is True
    assert result["snapshot_saved"] is True
    assert result["status"] == "SNAPSHOT_SCHEDULER_CYCLE_COMPLETE"
