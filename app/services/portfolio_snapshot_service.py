from datetime import datetime

from app.services.portfolio_aggregation_engine import PortfolioAggregationEngine
from app.services.portfolio_repository import PortfolioRepository


class PortfolioSnapshotService:

    def create_and_verify_snapshot(self):
        portfolio = PortfolioAggregationEngine().aggregate_empty_portfolio()
        repo = PortfolioRepository()

        save_result = repo.save_snapshot(portfolio)
        load_result = repo.load_latest_snapshot()

        verified = (
            save_result.get("saved") is True
            and load_result.get("found") is True
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "snapshot_created": save_result.get("saved", False),
            "snapshot_loaded": load_result.get("found", False),
            "snapshot_verified": verified,
            "execution_enabled": False,
            "status": "PORTFOLIO_SNAPSHOT_SERVICE_PASS" if verified else "PORTFOLIO_SNAPSHOT_SERVICE_FAIL"
        }
