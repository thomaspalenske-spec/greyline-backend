from datetime import datetime

from app.services.portfolio_repository import PortfolioRepository
from app.services.portfolio_state_engine import PortfolioStateEngine


class PortfolioIntegrityEngine:

    def evaluate_integrity(self):
        repo = PortfolioRepository()
        latest_snapshot = repo.load_latest_snapshot()
        portfolio_state = PortfolioStateEngine().evaluate_state()

        snapshot_found = latest_snapshot.get("found") is True
        state_valid = portfolio_state.get("status") in [
            "PORTFOLIO_STATE_ACTIVE",
            "NO_SNAPSHOT_FOUND"
        ]

        execution_disabled = portfolio_state.get("execution_enabled") is False

        healthy = (
            state_valid
            and execution_disabled
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "snapshot_found": snapshot_found,
            "state": portfolio_state.get("state"),
            "state_valid": state_valid,
            "execution_enabled": False,
            "integrity_healthy": healthy,
            "status": "PORTFOLIO_INTEGRITY_HEALTHY" if healthy else "PORTFOLIO_INTEGRITY_ERROR"
        }
