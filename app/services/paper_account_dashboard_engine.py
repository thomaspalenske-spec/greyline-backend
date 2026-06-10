from datetime import datetime

from app.services.paper_performance_summary_engine import (
    PaperPerformanceSummaryEngine
)


class PaperAccountDashboardEngine:

    def get_dashboard(self):

        performance = (
            PaperPerformanceSummaryEngine()
            .summarize()
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "account_type": "PAPER_TRADING",
            "starting_equity": performance.get("starting_equity"),
            "current_equity": performance.get("latest_equity"),
            "highest_equity": performance.get("highest_equity"),
            "total_return_pct": performance.get("total_return_pct"),
            "max_drawdown_pct": performance.get("max_drawdown_pct"),
            "snapshot_count": performance.get("snapshot_count"),
            "performance": performance,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "PAPER_ACCOUNT_DASHBOARD_READY"
        }
