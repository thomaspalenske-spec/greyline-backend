from datetime import datetime

from app.services.portfolio_repository import PortfolioRepository


class PortfolioStateEngine:

    def evaluate_state(self):
        repo = PortfolioRepository()
        snapshot = repo.load_latest_snapshot()

        if not snapshot.get("found"):
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "state": "EMPTY",
                "execution_enabled": False,
                "status": "NO_SNAPSHOT_FOUND"
            }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "state": "ACTIVE",
            "snapshot_found": True,
            "execution_enabled": False,
            "status": "PORTFOLIO_STATE_ACTIVE"
        }
