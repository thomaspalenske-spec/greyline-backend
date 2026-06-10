import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.governance_dashboard_engine import GovernanceDashboardEngine


def test_governance_dashboard_ready_when_integrity_passes():
    with patch("app.services.governance_dashboard_engine.IntegrityControlCenterEngine") as MockIntegrity:
        with patch("app.services.governance_dashboard_engine.GovernanceHealthEngine") as MockHealth:
            MockIntegrity.return_value.evaluate.return_value = {
                "integrity_pass": True,
                "status": "GREYLINE_INTEGRITY_READY",
                "position_reconciliation_status": "PASS",
                "portfolio_integrity": {"snapshot_found": True}
            }

            MockHealth.return_value.calculate_health.return_value = {
                "health_score": 100,
                "health_level": "GREEN",
                "status": "GOVERNANCE_HEALTHY"
            }

            result = GovernanceDashboardEngine().get_dashboard()

    assert result["status"] == "GOVERNANCE_DASHBOARD_READY"
    assert result["health_score"] == 100
    assert result["execution_allowed"] is False
    assert result["order_placement_allowed"] is False


def test_governance_dashboard_blocks_when_integrity_fails():
    with patch("app.services.governance_dashboard_engine.IntegrityControlCenterEngine") as MockIntegrity:
        with patch("app.services.governance_dashboard_engine.GovernanceHealthEngine") as MockHealth:
            MockIntegrity.return_value.evaluate.return_value = {
                "integrity_pass": False,
                "status": "GREYLINE_INTEGRITY_BLOCKED",
                "position_reconciliation_status": "FAIL",
                "portfolio_integrity": {"snapshot_found": False}
            }

            MockHealth.return_value.calculate_health.return_value = {
                "health_score": 55,
                "health_level": "RED",
                "status": "GOVERNANCE_DEGRADED"
            }

            result = GovernanceDashboardEngine().get_dashboard()

    assert result["status"] == "GOVERNANCE_DASHBOARD_BLOCKED"
    assert result["integrity_pass"] is False
    assert result["health_level"] == "RED"
