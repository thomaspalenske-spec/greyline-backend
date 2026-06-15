from datetime import datetime

from app.services.live_portfolio_snapshot_builder import LivePortfolioSnapshotBuilder
from app.services.live_portfolio_snapshot_repository import LivePortfolioSnapshotRepository


class LivePortfolioHealthDashboardService:

    def get_health_status(self):
        snapshot = LivePortfolioSnapshotBuilder().build_snapshot()
        latest = LivePortfolioSnapshotRepository().load_latest_snapshot()

        broker_healthy = (
            snapshot.get("snapshot_healthy", False)
            or snapshot.get("raw_snapshot", {}).get("snapshot_healthy", False)
            or snapshot.get("normalized_snapshot", {}).get("snapshot_healthy", False)
        )
        persistence_healthy = latest.get("found", False)

        overall_healthy = broker_healthy and persistence_healthy

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker_feed_healthy": broker_healthy,
            "snapshot_repository_healthy": persistence_healthy,
            "overall_healthy": overall_healthy,
            "execution_enabled": False,
            "status": (
                "LIVE_PORTFOLIO_HEALTHY"
                if overall_healthy
                else "LIVE_PORTFOLIO_DEGRADED"
            )
        }
