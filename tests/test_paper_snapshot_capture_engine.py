import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_snapshot_capture_engine import PaperSnapshotCaptureEngine


def test_snapshot_capture_creates_and_saves_snapshot():
    with patch("app.services.paper_snapshot_capture_engine.PaperAccountSnapshotEngine") as MockSnapshot:
        with patch("app.services.paper_snapshot_capture_engine.PaperAccountSnapshotRepository") as MockRepo:
            MockSnapshot.return_value.create_snapshot.return_value = {
                "equity": 10000.0,
                "status": "ACCOUNT_SNAPSHOT_CREATED"
            }

            MockRepo.return_value.append_snapshot.return_value = {
                "snapshot_saved": True,
                "snapshot_count": 1,
                "status": "SNAPSHOT_SAVED"
            }

            result = PaperSnapshotCaptureEngine().capture(
                cash_balance=10000.0,
                positions=[]
            )

    assert result["snapshot_saved"] is True
    assert result["status"] == "SNAPSHOT_CAPTURE_COMPLETE"
    assert result["snapshot"]["equity"] == 10000.0
