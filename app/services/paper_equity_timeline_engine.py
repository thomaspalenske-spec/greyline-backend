from datetime import datetime

from app.services.paper_account_snapshot_repository import (
    PaperAccountSnapshotRepository
)


class PaperEquityTimelineEngine:

    def build_timeline(self):
        snapshots = (
            PaperAccountSnapshotRepository()
            .get_snapshots()
        )

        timeline = []

        for snapshot in snapshots:
            timeline.append(
                {
                    "timestamp":
                        snapshot.get(
                            "snapshot_timestamp"
                        ),
                    "equity":
                        snapshot.get(
                            "equity",
                            0
                        )
                }
            )

        highest_equity = max(
            [x["equity"] for x in timeline],
            default=0
        )

        latest_equity = (
            timeline[-1]["equity"]
            if timeline
            else 0
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "timeline": timeline,
            "snapshot_count": len(timeline),
            "latest_equity": latest_equity,
            "highest_equity": highest_equity,
            "status": "EQUITY_TIMELINE_READY"
        }
