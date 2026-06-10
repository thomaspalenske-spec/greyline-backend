from datetime import datetime

from app.services.paper_equity_timeline_engine import (
    PaperEquityTimelineEngine
)
from app.services.paper_drawdown_engine import (
    PaperDrawdownEngine
)


class PaperPerformanceSummaryEngine:

    def summarize(self):

        timeline = (
            PaperEquityTimelineEngine()
            .build_timeline()
        )

        drawdown = (
            PaperDrawdownEngine()
            .calculate()
        )

        latest_equity = timeline.get(
            "latest_equity",
            0
        )

        highest_equity = timeline.get(
            "highest_equity",
            0
        )

        starting_equity = (
            timeline["timeline"][0]["equity"]
            if timeline.get("timeline")
            else 0
        )

        total_return_pct = 0

        if starting_equity > 0:
            total_return_pct = (
                (
                    latest_equity
                    - starting_equity
                )
                / starting_equity
            ) * 100

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "starting_equity": starting_equity,
            "latest_equity": latest_equity,
            "highest_equity": highest_equity,
            "total_return_pct": round(
                total_return_pct,
                2
            ),
            "max_drawdown_pct":
                drawdown.get(
                    "max_drawdown_pct",
                    0
                ),
            "snapshot_count":
                timeline.get(
                    "snapshot_count",
                    0
                ),
            "status":
                "PERFORMANCE_SUMMARY_READY"
        }
