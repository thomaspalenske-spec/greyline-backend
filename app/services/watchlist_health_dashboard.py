from datetime import datetime

from app.services.watchlist_reader import WatchlistReader
from app.services.watchlist_analytics_engine import WatchlistAnalyticsEngine


class WatchlistHealthDashboard:

    def get_health(self):
        reader = WatchlistReader().read_watchlist()
        analytics = WatchlistAnalyticsEngine().analyze_watchlist()

        healthy = (
            reader.get("watchlist_found") is True
            and analytics.get("integrity_ok") is True
            and analytics.get("execution_enabled") is False
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "watchlist_found": reader.get("watchlist_found"),
            "symbol_count": reader.get("symbol_count"),
            "analytics_status": analytics.get("status"),
            "integrity_ok": analytics.get("integrity_ok"),
            "execution_enabled": False,
            "watchlist_healthy": healthy,
            "status": "WATCHLIST_HEALTHY" if healthy else "WATCHLIST_DEGRADED"
        }
