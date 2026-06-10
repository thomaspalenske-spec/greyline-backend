from datetime import datetime

from app.services.integrity_control_center_engine import IntegrityControlCenterEngine
from app.services.governance_health_engine import GovernanceHealthEngine


class GovernanceDashboardEngine:

    def get_dashboard(self):
        integrity = IntegrityControlCenterEngine().evaluate()

        health = GovernanceHealthEngine().calculate_health(
            integrity_pass=integrity.get("integrity_pass"),
            reconciliation_status=integrity.get("position_reconciliation_status"),
            lifecycle_valid=True,
            drift_detected=False,
            snapshot_valid=integrity.get("portfolio_integrity", {}).get("snapshot_found", True)
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "GOVERNANCE_DASHBOARD",
            "health_score": health.get("health_score"),
            "health_level": health.get("health_level"),
            "health_status": health.get("status"),
            "integrity_pass": integrity.get("integrity_pass"),
            "integrity_status": integrity.get("status"),
            "position_reconciliation_status": integrity.get("position_reconciliation_status"),
            "execution_allowed": False,
            "order_placement_allowed": False,
            "integrity_control_center": integrity,
            "governance_health": health,
            "status": "GOVERNANCE_DASHBOARD_READY" if integrity.get("integrity_pass") else "GOVERNANCE_DASHBOARD_BLOCKED"
        }
