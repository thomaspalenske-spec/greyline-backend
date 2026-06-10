import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.integrity_control_center_engine import IntegrityControlCenterEngine


def test_integrity_control_center_ready_when_all_checks_pass():
    with patch("app.services.integrity_control_center_engine.PortfolioIntegrityEngine") as MockPortfolio:
        with patch("app.services.integrity_control_center_engine.PositionReconciliationEngine") as MockReconciliation:
            MockPortfolio.return_value.evaluate_integrity.return_value = {
                "integrity_healthy": True,
                "status": "PORTFOLIO_INTEGRITY_HEALTHY"
            }
            MockReconciliation.return_value.reconcile_positions.return_value = {
                "reconciliation_status": "PASS"
            }

            result = IntegrityControlCenterEngine().evaluate()

    assert result["integrity_pass"] is True
    assert result["execution_allowed"] is False
    assert result["order_placement_allowed"] is False
    assert result["status"] == "GREYLINE_INTEGRITY_READY"


def test_integrity_control_center_blocks_when_portfolio_integrity_fails():
    with patch("app.services.integrity_control_center_engine.PortfolioIntegrityEngine") as MockPortfolio:
        with patch("app.services.integrity_control_center_engine.PositionReconciliationEngine") as MockReconciliation:
            MockPortfolio.return_value.evaluate_integrity.return_value = {
                "integrity_healthy": False,
                "status": "PORTFOLIO_INTEGRITY_ERROR"
            }
            MockReconciliation.return_value.reconcile_positions.return_value = {
                "reconciliation_status": "PASS"
            }

            result = IntegrityControlCenterEngine().evaluate()

    assert result["integrity_pass"] is False
    assert result["status"] == "GREYLINE_INTEGRITY_BLOCKED"


def test_integrity_control_center_blocks_when_reconciliation_fails():
    with patch("app.services.integrity_control_center_engine.PortfolioIntegrityEngine") as MockPortfolio:
        with patch("app.services.integrity_control_center_engine.PositionReconciliationEngine") as MockReconciliation:
            MockPortfolio.return_value.evaluate_integrity.return_value = {
                "integrity_healthy": True,
                "status": "PORTFOLIO_INTEGRITY_HEALTHY"
            }
            MockReconciliation.return_value.reconcile_positions.return_value = {
                "reconciliation_status": "FAIL"
            }

            result = IntegrityControlCenterEngine().evaluate()

    assert result["integrity_pass"] is False
    assert result["status"] == "GREYLINE_INTEGRITY_BLOCKED"
