"""Regression tests for the reconciliation audit batch (#2, #3, #7, #9)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---- #2: connection watchdog account id is config-driven, not hardcoded ----
def test_watchdog_account_ok_reflects_configured_id():
    MOD = "app.services.greyline_connection_watchdog_engine"
    from app.services.greyline_connection_watchdog_engine import GreyLineConnectionWatchdogEngine

    def fake_getenv(key, default=None):
        return {"TRADESTATION_MARGIN_ACCOUNT_ID": "99887766"}.get(key, default)

    with patch(f"{MOD}.TradeStationTokenMaintenanceEngine"), \
         patch(f"{MOD}.TradeStationAccountDiscoveryLiveEngine"), \
         patch(f"{MOD}.LiveBrokerSummaryEngine") as MockSummary, \
         patch(f"{MOD}.TradeStationPositionsLiveEngine"), \
         patch(f"{MOD}.TradeStationOrdersLiveEngine"), \
         patch(f"{MOD}.BackgroundSchedulerService") as MockSched, \
         patch(f"{MOD}.ImmutableAuditLedgerEngine"), \
         patch(f"{MOD}.getenv", side_effect=fake_getenv):
        MockSched.status.return_value = {"scheduler_enabled": True, "thread_alive": True}
        MockSummary.return_value.summarize.return_value = {
            "account_id": "99887766", "status": "LIVE_ACCOUNT_READY",
        }
        assert GreyLineConnectionWatchdogEngine().run()["default_account_ok"] is True

        MockSummary.return_value.summarize.return_value = {
            "account_id": "00000000", "status": "LIVE_ACCOUNT_READY",
        }
        assert GreyLineConnectionWatchdogEngine().run()["default_account_ok"] is False


def test_watchdog_fails_safe_when_account_id_unconfigured():
    MOD = "app.services.greyline_connection_watchdog_engine"
    from app.services.greyline_connection_watchdog_engine import GreyLineConnectionWatchdogEngine

    with patch(f"{MOD}.TradeStationTokenMaintenanceEngine"), \
         patch(f"{MOD}.TradeStationAccountDiscoveryLiveEngine"), \
         patch(f"{MOD}.LiveBrokerSummaryEngine") as MockSummary, \
         patch(f"{MOD}.TradeStationPositionsLiveEngine"), \
         patch(f"{MOD}.TradeStationOrdersLiveEngine"), \
         patch(f"{MOD}.BackgroundSchedulerService") as MockSched, \
         patch(f"{MOD}.ImmutableAuditLedgerEngine"), \
         patch(f"{MOD}.getenv", side_effect=lambda k, d=None: d):
        MockSched.status.return_value = {"scheduler_enabled": True, "thread_alive": True}
        MockSummary.return_value.summarize.return_value = {
            "account_id": "99887766", "status": "LIVE_ACCOUNT_READY",
        }
        assert GreyLineConnectionWatchdogEngine().run()["default_account_ok"] is False


# ---- #3: institutional command center reflects the governor, not a literal ----
def test_institutional_command_center_reflects_governor():
    MOD = "app.services.greyline_institutional_command_center"
    from app.services.greyline_institutional_command_center import GreyLineInstitutionalCommandCenter

    with patch(f"{MOD}.LeadershipRotationSummaryEngine"), \
         patch(f"{MOD}.SectorRotationSummaryEngine"), \
         patch(f"{MOD}.CrossAssetFlowSummaryEngine"), \
         patch(f"{MOD}.OpportunitySummaryEngine") as MockOpp, \
         patch(f"{MOD}.InstitutionalFlowSummaryEngine"), \
         patch(f"{MOD}.ExecutionGovernor") as MockGovernor:
        MockOpp.return_value.get_summary.return_value = {"opportunities": []}
        MockGovernor.return_value.evaluate_execution_permission.return_value = {
            "execution_enabled": True, "order_placement_allowed": True,
        }
        result = GreyLineInstitutionalCommandCenter().get_command_center()

    assert result["execution_enabled"] is True
    assert result["order_placement_allowed"] is True


# ---- #7: readiness scoring engine imports (stray syntax lines removed) ----
def test_readiness_scoring_engine_imports_cleanly():
    import importlib
    mod = importlib.import_module("app.services.readiness_scoring_engine")
    assert hasattr(mod, "ReadinessScoringEngine")


# ---- #9: readiness fix engine reports real state, not permanent UNKNOWN ----
def test_readiness_fix_engine_reports_real_state():
    MOD = "app.services.readiness_fix_engine"
    from app.services.readiness_fix_engine import ReadinessFixEngine

    with patch(f"{MOD}.ReadinessAggregationEngine") as MockAgg:
        MockAgg.return_value.evaluate.return_value = {
            "status": "READY", "config_registry": [],
        }
        assert ReadinessFixEngine().evaluate()["state"] == "READY"
