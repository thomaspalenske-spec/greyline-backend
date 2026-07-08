from datetime import datetime
from app.services.execution_governor import ExecutionGovernor

from app.services.paper_performance_summary_engine import (
    PaperPerformanceSummaryEngine
)


class PaperAccountDashboardEngine:

    def get_dashboard(self):

        performance = (
            PaperPerformanceSummaryEngine()
            .summarize()
        )

        execution_permission = ExecutionGovernor().evaluate_execution_permission("EXECUTE")

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
            "execution_permission": execution_permission,
            "execution_enabled": execution_permission.get("execution_enabled"),
            "order_placement_allowed": execution_permission.get("order_placement_allowed"),
            "status": "PAPER_ACCOUNT_DASHBOARD_READY"
        }
