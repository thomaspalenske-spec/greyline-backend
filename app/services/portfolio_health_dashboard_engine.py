from datetime import datetime

from app.services.portfolio_state_engine import PortfolioStateEngine
from app.services.portfolio_integrity_engine import PortfolioIntegrityEngine


class PortfolioHealthDashboardEngine:

    def get_dashboard(self):
        state = PortfolioStateEngine().evaluate_state()
        integrity = PortfolioIntegrityEngine().evaluate_integrity()

        portfolio_healthy = (
            state.get("execution_enabled") is False
            and integrity.get("integrity_healthy") is True
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "portfolio_state": state.get("state"),
            "portfolio_state_status": state.get("status"),
            "integrity_healthy": integrity.get("integrity_healthy"),
            "integrity_status": integrity.get("status"),
            "execution_enabled": False,
            "portfolio_healthy": portfolio_healthy,
            "status": "PORTFOLIO_HEALTHY" if portfolio_healthy else "PORTFOLIO_DEGRADED"
        }
