from datetime import datetime

from app.services.paper_account_snapshot_engine import PaperAccountSnapshotEngine
from app.services.paper_account_snapshot_repository import PaperAccountSnapshotRepository


class PaperSnapshotCaptureEngine:

    def capture(self, cash_balance, positions):
        snapshot = PaperAccountSnapshotEngine().create_snapshot(
            cash_balance=cash_balance,
            positions=positions
        )

        save_result = PaperAccountSnapshotRepository().append_snapshot(snapshot)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "snapshot": snapshot,
            "save_result": save_result,
            "snapshot_saved": save_result.get("snapshot_saved", False),
            "status": "SNAPSHOT_CAPTURE_COMPLETE"
        }
