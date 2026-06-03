from datetime import datetime

from app.services.portfolio_analytics_engine import PortfolioAnalyticsEngine
from app.services.portfolio_analytics_repository import PortfolioAnalyticsRepository


class PortfolioAnalyticsPersistenceService:

    def save_and_verify_analytics(self):
        analytics = PortfolioAnalyticsEngine().analyze()

        repo = PortfolioAnalyticsRepository()

        save_result = repo.save_analytics(analytics)
        load_result = repo.load_latest_analytics()

        verified = (
            save_result.get("saved") is True
            and load_result.get("found") is True
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "analytics_status": analytics.get("status"),
            "analytics_saved": save_result.get("saved"),
            "analytics_loaded": load_result.get("found"),
            "analytics_verified": verified,
            "execution_enabled": False,
            "status": (
                "PORTFOLIO_ANALYTICS_PERSISTED"
                if verified
                else "PORTFOLIO_ANALYTICS_PERSISTENCE_FAILED"
            )
        }
