from datetime import datetime

from app.services.live_portfolio_health_dashboard_service import LivePortfolioHealthDashboardService
from app.services.live_portfolio_snapshot_builder import LivePortfolioSnapshotBuilder
from app.services.portfolio_analytics_reader import PortfolioAnalyticsReader


class PortfolioDashboardService:

    def get_dashboard(self):
        snapshot = LivePortfolioSnapshotBuilder().build_snapshot()
        analytics = PortfolioAnalyticsReader().read_latest()
        health = LivePortfolioHealthDashboardService().get_health_status()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "dashboard_ready": True,
            "snapshot_status": snapshot.get("status"),
            "analytics_status": analytics.get("status"),
            "health_status": health.get("status"),
            "snapshot": snapshot,
            "analytics": analytics,
            "health": health,
            "execution_enabled": False,
            "status": "PORTFOLIO_DASHBOARD_READY"
        }
