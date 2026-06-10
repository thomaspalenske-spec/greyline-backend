from datetime import datetime

from app.services.paper_snapshot_capture_engine import (
    PaperSnapshotCaptureEngine
)


class PaperSnapshotSchedulerEngine:

    def run_cycle(
        self,
        cash_balance,
        positions
    ):

        result = (
            PaperSnapshotCaptureEngine()
            .capture(
                cash_balance=cash_balance,
                positions=positions
            )
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cycle_completed": True,
            "snapshot_saved":
                result.get(
                    "snapshot_saved",
                    False
                ),
            "capture_result": result,
            "status":
                "SNAPSHOT_SCHEDULER_CYCLE_COMPLETE"
        }
