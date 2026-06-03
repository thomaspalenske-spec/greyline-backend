from datetime import datetime

from app.services.portfolio_dashboard_service import PortfolioDashboardService


class PortfolioSummaryEngine:

    def get_summary(self):
        dashboard = PortfolioDashboardService().get_dashboard()

        analytics = dashboard.get("analytics", {})
        health = dashboard.get("health", {})
        snapshot = dashboard.get("snapshot", {})

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "dashboard_status": dashboard.get("status"),
            "snapshot_status": dashboard.get("snapshot_status"),
            "analytics_status": dashboard.get("analytics_status"),
            "health_status": dashboard.get("health_status"),
            "timeline_points": (
                analytics.get("analytics", {}) or {}
            ).get("timeline_points"),
            "data_integrity_score": (
                analytics.get("analytics", {}) or {}
            ).get("data_integrity_score"),
            "portfolio_health_score": (
                analytics.get("analytics", {}) or {}
            ).get("portfolio_health_score"),
            "snapshot_healthy": snapshot.get("snapshot_healthy"),
            "overall_healthy": health.get("overall_healthy"),
            "execution_enabled": False,
            "status": "PORTFOLIO_SUMMARY_READY"
        }
