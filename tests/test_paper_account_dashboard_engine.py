import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_account_dashboard_engine import PaperAccountDashboardEngine


PERFORMANCE = {
    "starting_equity": 10000,
    "latest_equity": 11000,
    "highest_equity": 12000,
    "total_return_pct": 10.0,
    "max_drawdown_pct": 5.0,
    "snapshot_count": 3,
}


def _run(execution_enabled, order_placement_allowed):
    # Mock BOTH dependencies so the test is deterministic and does not read the
    # ambient .env / process environment. The engine must faithfully reflect
    # whatever ExecutionGovernor reports, in either armed or disarmed state.
    with patch("app.services.paper_account_dashboard_engine.PaperPerformanceSummaryEngine") as MockPerformance, \
         patch("app.services.paper_account_dashboard_engine.ExecutionGovernor") as MockGovernor:
        MockPerformance.return_value.summarize.return_value = PERFORMANCE
        MockGovernor.return_value.evaluate_execution_permission.return_value = {
            "execution_enabled": execution_enabled,
            "order_placement_allowed": order_placement_allowed,
        }
        return PaperAccountDashboardEngine().get_dashboard()


def test_paper_account_dashboard_ready():
    result = _run(execution_enabled=False, order_placement_allowed=False)

    assert result["account_type"] == "PAPER_TRADING"
    assert result["current_equity"] == 11000
    assert result["highest_equity"] == 12000
    assert result["total_return_pct"] == 10.0
    assert result["max_drawdown_pct"] == 5.0
    assert result["execution_enabled"] is False
    assert result["order_placement_allowed"] is False
    assert result["status"] == "PAPER_ACCOUNT_DASHBOARD_READY"


def test_paper_account_dashboard_reflects_armed_state():
    # When the kill-switch is armed, the dashboard must report it — not hardcode False.
    result = _run(execution_enabled=True, order_placement_allowed=True)

    assert result["execution_enabled"] is True
    assert result["order_placement_allowed"] is True
    assert result["status"] == "PAPER_ACCOUNT_DASHBOARD_READY"
