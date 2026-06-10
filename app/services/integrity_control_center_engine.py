from datetime import datetime

from app.services.portfolio_integrity_engine import PortfolioIntegrityEngine
from app.services.position_reconciliation_engine import PositionReconciliationEngine


class IntegrityControlCenterEngine:

    def evaluate(self):
        portfolio_integrity = PortfolioIntegrityEngine().evaluate_integrity()
        position_reconciliation = PositionReconciliationEngine().reconcile_positions()

        portfolio_ok = portfolio_integrity.get("integrity_healthy") is True
        reconciliation_ok = (
            position_reconciliation.get("reconciliation_status") == "PASS"
        )

        integrity_pass = (
            portfolio_ok
            and reconciliation_ok
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "integrity_pass": integrity_pass,
            "execution_allowed": False,
            "order_placement_allowed": False,
            "portfolio_integrity_status": portfolio_integrity.get("status"),
            "position_reconciliation_status": position_reconciliation.get("reconciliation_status"),
            "portfolio_integrity": portfolio_integrity,
            "position_reconciliation": position_reconciliation,
            "status": "GREYLINE_INTEGRITY_READY" if integrity_pass else "GREYLINE_INTEGRITY_BLOCKED"
        }
