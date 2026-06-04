from fastapi import FastAPI

app = FastAPI(title="GreyLine Backend Server")


@app.get("/")
def home():
    return {
        "system": "GreyLine",
        "status": "ONLINE"
    }


@app.get("/readiness")
def readiness():
    return {
        "system": "GreyLine",
        "status": "ONLINE",
        "broker_layer": "INSTALLED",
        "sandbox_readiness_engine": "AVAILABLE",
        "credential_validation_engine": "AVAILABLE",
        "version": "0.0.1"
    }


from app.services.paper_trading_command_center_engine import PaperTradingCommandCenterEngine


@app.get("/paper-trading-command-center")
def paper_trading_command_center():
    engine = PaperTradingCommandCenterEngine()
    return engine.get_command_center()


from app.services.ledger_engine import LedgerEngine
from app.services.snapshot_engine import SnapshotEngine
from app.services.account_engine import AccountEngine
from app.services.position_reconciliation_engine import PositionReconciliationEngine
from app.services.system_status_engine import SystemStatusEngine
from app.services.backend_readiness_engine import BackendReadinessEngine
from app.services.backend_manifest_engine import BackendManifestEngine


@app.get("/ledger")
def ledger():
    return LedgerEngine().load()


@app.get("/snapshot")
def snapshot():
    return SnapshotEngine().create_snapshot({'system': 'GreyLine', 'snapshot_test': True})


@app.get("/account")
def account():
    return AccountEngine().get_account_status()


@app.get("/reconcile")
def reconcile():
    return PositionReconciliationEngine().reconcile_positions()


@app.get("/system-status")
def system_status():
    return SystemStatusEngine().get_status()


@app.get("/backend-readiness")
def backend_readiness():
    return BackendReadinessEngine().evaluate_readiness(
        api_online=True,
        ledger_online=True,
        snapshot_online=True,
        reconciliation_online=True,
        account_health="HEALTHY"
    )


@app.get("/manifest")
def manifest():
    return BackendManifestEngine().get_manifest()


from app.services.runtime_configuration_engine import RuntimeConfigurationEngine
from app.services.runtime_safety_summary_engine import RuntimeSafetySummaryEngine
from app.services.deployment_mode_gate_engine import DeploymentModeGateEngine
from app.services.configuration_validation_engine import ConfigurationValidationEngine


@app.get("/runtime-configuration")
def runtime_configuration():
    return RuntimeConfigurationEngine().get_runtime_configuration()


@app.get("/runtime-safety")
def runtime_safety():
    return RuntimeSafetySummaryEngine().summarize_runtime_safety(
        broker_connected=False,
        autonomous_execution_enabled=False,
        authority_level="OBSERVE_RECOMMEND_ONLY",
        kill_switch_status="STANDBY",
        credential_safety_approved=True
    )


@app.get("/deployment-mode-gate")
def deployment_mode_gate():
    return DeploymentModeGateEngine().evaluate_mode(
        requested_mode="PAPER_TRADING_PREP"
    )


@app.get("/configuration-validation")
def configuration_validation():
    return ConfigurationValidationEngine().validate_configuration(
        {
            "GREYLINE_MODE": "LOCAL_DEVELOPMENT",
            "GREYLINE_ENVIRONMENT": "MacBook",
            "BROKER_CONNECTION_ENABLED": False,
            "AUTONOMOUS_EXECUTION_ENABLED": False
        }
    )


from app.services.paper_trading_prep_gate_engine import PaperTradingPrepGateEngine
from app.services.paper_trading_blocker_engine import PaperTradingBlockerEngine
from app.services.paper_trading_approval_gate_engine import PaperTradingApprovalGateEngine
from app.services.paper_trading_control_center_engine import PaperTradingControlCenterEngine


@app.get("/paper-trading-prep-gate")
def paper_trading_prep_gate():
    return PaperTradingPrepGateEngine().evaluate_prep_gate(
        backend_ready=True,
        broker_safety_ready=True,
        credential_safety_ready=True,
        authority_gate_ready=True,
        kill_switch_ready=True
    )


@app.get("/paper-trading-blockers")
def paper_trading_blockers():
    return PaperTradingBlockerEngine().evaluate_blockers()


@app.get("/paper-trading-approval-gate")
def paper_trading_approval_gate():
    return PaperTradingApprovalGateEngine().evaluate_approval(
        paper_trading_ready=False,
        manual_approval_granted=False
    )


@app.get("/paper-trading-control-center")
def paper_trading_control_center():
    return PaperTradingControlCenterEngine().get_control_center()


from app.services.paper_trading_transition_summary_engine import PaperTradingTransitionSummaryEngine
from app.services.paper_trading_launch_checklist_engine import PaperTradingLaunchChecklistEngine
from app.services.paper_trading_final_gate_engine import PaperTradingFinalGateEngine
from app.services.paper_trading_phase_summary_engine import PaperTradingPhaseSummaryEngine


@app.get("/paper-trading-transition-summary")
def paper_trading_transition_summary():
    return PaperTradingTransitionSummaryEngine().summarize_transition(
        paper_trading_ready=False,
        approval_passed=False,
        broker_connected=False,
        api_credentials_configured=False
    )


@app.get("/paper-trading-launch-checklist")
def paper_trading_launch_checklist():
    return PaperTradingLaunchChecklistEngine().get_checklist()


@app.get("/paper-trading-final-gate")
def paper_trading_final_gate():
    return PaperTradingFinalGateEngine().evaluate_final_gate(
        paper_trading_ready=False,
        approval_passed=False,
        blockers_cleared=False,
        launch_checklist_complete=False
    )


@app.get("/paper-trading-phase-summary")
def paper_trading_phase_summary():
    return PaperTradingPhaseSummaryEngine().get_phase_summary()


from app.services.credential_safety_gate_engine import CredentialSafetyGateEngine
from app.services.credential_storage_policy_engine import CredentialStoragePolicyEngine
from app.services.environment_file_guard_engine import EnvironmentFileGuardEngine
from app.services.broker_safety_summary_engine import BrokerSafetySummaryEngine
from app.services.broker_sandbox_connection_plan_engine import BrokerSandboxConnectionPlanEngine


@app.get("/credential-safety-gate")
def credential_safety_gate():
    return CredentialSafetyGateEngine().evaluate_credential_safety(
        credentials_in_plaintext=False,
        env_file_present=True,
        gitignore_protects_env=True,
        credential_rotation_required=False
    )


@app.get("/credential-storage-policy")
def credential_storage_policy():
    return CredentialStoragePolicyEngine().get_policy()


@app.get("/environment-file-guard")
def environment_file_guard():
    return EnvironmentFileGuardEngine().evaluate_environment_guard()


@app.get("/broker-safety-summary")
def broker_safety_summary():
    return BrokerSafetySummaryEngine().summarize_safety(safe_for_broker_prep=True, authority_approved=True, execution_blocked=False, kill_switch_status='STANDBY', trading_allowed=False)


@app.get("/broker-sandbox-plan")
def broker_sandbox_plan():
    return BrokerSandboxConnectionPlanEngine().get_plan()


from app.services.tradestation_readiness_checklist_engine import TradeStationReadinessChecklistEngine
from app.services.tradestation_sandbox_readiness_engine import TradeStationSandboxReadinessEngine
from app.services.tradestation_credential_validation_engine import TradeStationCredentialValidationEngine
from app.services.api_credential_readiness_engine import ApiCredentialReadinessEngine
from app.services.broker_integration_readiness_engine import BrokerIntegrationReadinessEngine
from app.services.broker_integration_blocker_engine import BrokerIntegrationBlockerEngine


@app.get("/tradestation-readiness")
def tradestation_readiness():
    return TradeStationReadinessChecklistEngine().evaluate_checklist()


@app.get("/tradestation-sandbox-readiness")
def tradestation_sandbox_readiness():
    return TradeStationSandboxReadinessEngine().evaluate()


@app.get("/tradestation-credential-validation")
def tradestation_credential_validation():
    return TradeStationCredentialValidationEngine().evaluate()


@app.get("/api-credential-readiness")
def api_credential_readiness():
    return ApiCredentialReadinessEngine().evaluate_credentials()


@app.get("/broker-integration-readiness")
def broker_integration_readiness():
    return BrokerIntegrationReadinessEngine().evaluate_readiness(ledger_supremacy_active=True, audit_log_active=True, snapshot_restore_active=True, reconciliation_active=True, drift_detection_active=True, autonomous_execution_enabled=False)


@app.get("/broker-integration-blockers")
def broker_integration_blockers():
    return BrokerIntegrationBlockerEngine().evaluate_blockers()


from app.services.account_drift_detector_engine import AccountDriftDetectorEngine
from app.services.account_health_engine import AccountHealthEngine
from app.services.audit_log_engine import AuditLogEngine
from app.services.backend_capability_registry_engine import BackendCapabilityRegistryEngine
from app.services.backend_control_center_engine import BackendControlCenterEngine
from app.services.backend_phase_gate_engine import BackendPhaseGateEngine
from app.services.backend_ucf_registry_engine import BackendUcfRegistryEngine
from app.services.restore_engine import RestoreEngine


@app.get("/account-drift")
def account_drift():
    return AccountDriftDetectorEngine().detect_drift(ledger_equity=10000, reported_equity=10000)


@app.get("/account-health")
def account_health():
    return AccountHealthEngine().evaluate_health(reconciliation_status='PASS', drift_detected=False, snapshot_valid=True)


@app.get("/audit-log")
def audit_log():
    return AuditLogEngine().create_log(action='AUDIT_TEST', status='PASS', details={'system': 'GreyLine'})


@app.get("/backend-capabilities")
def backend_capabilities():
    return BackendCapabilityRegistryEngine().list_capabilities()


@app.get("/backend-control-center")
def backend_control_center():
    return BackendControlCenterEngine().get_control_center()


@app.get("/backend-phase-gate")
def backend_phase_gate():
    return BackendPhaseGateEngine().evaluate_phase_gate(backend_ready=True, control_center_online=True, ucf_registry_active=True, capability_registry_active=True, milestone_registry_active=True)


@app.get("/backend-ucfs")
def backend_ucfs():
    return BackendUcfRegistryEngine().list_ucfs()


@app.get("/restore")
def restore():
    return RestoreEngine().restore_snapshot('app/snapshots/snapshot_20260530_131732.json')

from app.services.trade_station_engine import TradeStationEngine


@app.get("/tradestation-status")
def tradestation_status():
    return TradeStationEngine().evaluate()


from app.services.tradestation_oauth_readiness_engine import TradeStationOAuthReadinessEngine


@app.get("/tradestation-oauth-readiness")
def tradestation_oauth_readiness():
    return TradeStationOAuthReadinessEngine().evaluate()


from app.services.tradestation_account_discovery_engine import TradeStationAccountDiscoveryEngine


@app.get("/tradestation-account-discovery")
def tradestation_account_discovery():
    return TradeStationAccountDiscoveryEngine().evaluate()


from app.services.tradestation_read_only_client import TradeStationReadOnlyClient


@app.get("/tradestation-read-only-client")
def tradestation_read_only_client():
    return TradeStationReadOnlyClient().evaluate()


from app.services.tradestation_endpoint_map_engine import TradeStationEndpointMapEngine


@app.get("/tradestation-endpoint-map")
def tradestation_endpoint_map():
    return TradeStationEndpointMapEngine().get_endpoint_map()


from app.services.tradestation_integration_dashboard_engine import TradeStationIntegrationDashboardEngine


@app.get("/tradestation-dashboard")
def tradestation_dashboard():
    return TradeStationIntegrationDashboardEngine().get_dashboard()


from app.services.portfolio_data_model_engine import PortfolioDataModelEngine


@app.get("/portfolio-schema")
def portfolio_schema():
    return PortfolioDataModelEngine().get_schema()


from app.services.portfolio_snapshot_model_engine import PortfolioSnapshotModelEngine


@app.get("/portfolio-snapshot-model")
def portfolio_snapshot_model():
    return PortfolioSnapshotModelEngine().create_empty_snapshot()


from app.services.portfolio_position_model_engine import PortfolioPositionModelEngine


@app.get("/portfolio-position-model")
def portfolio_position_model():
    return PortfolioPositionModelEngine().create_empty_position()


from app.services.portfolio_order_model_engine import PortfolioOrderModelEngine


@app.get("/portfolio-order-model")
def portfolio_order_model():
    return PortfolioOrderModelEngine().create_empty_order()


from app.services.portfolio_balance_model_engine import PortfolioBalanceModelEngine


@app.get("/portfolio-balance-model")
def portfolio_balance_model():
    return PortfolioBalanceModelEngine().create_empty_balance()


from app.services.portfolio_account_model_engine import PortfolioAccountModelEngine


@app.get("/portfolio-account-model")
def portfolio_account_model():
    return PortfolioAccountModelEngine().create_empty_account()


from app.services.portfolio_aggregation_engine import PortfolioAggregationEngine


@app.get("/portfolio")
def portfolio():
    return PortfolioAggregationEngine().aggregate_empty_portfolio()


from app.services.portfolio_repository import PortfolioRepository


@app.get("/portfolio-repository-test")
def portfolio_repository_test():
    repo = PortfolioRepository()

    snapshot = {
        "account_id": None,
        "cash_balance": 0.0,
        "equity": 0.0,
        "positions": [],
        "open_orders": [],
        "source": "TEST_ONLY",
        "execution_enabled": False
    }

    save_result = repo.save_snapshot(snapshot)
    load_result = repo.load_latest_snapshot()

    return {
        "save_result": save_result,
        "load_result": load_result,
        "execution_enabled": False,
        "status": "PORTFOLIO_REPOSITORY_TEST_PASS"
    }


from app.services.portfolio_snapshot_service import PortfolioSnapshotService


@app.get("/portfolio-snapshot-service")
def portfolio_snapshot_service():
    return PortfolioSnapshotService().create_and_verify_snapshot()


from app.services.portfolio_state_engine import PortfolioStateEngine


@app.get("/portfolio-state")
def portfolio_state():
    return PortfolioStateEngine().evaluate_state()


from app.services.portfolio_integrity_engine import PortfolioIntegrityEngine


@app.get("/portfolio-integrity")
def portfolio_integrity():
    return PortfolioIntegrityEngine().evaluate_integrity()


from app.services.portfolio_health_dashboard_engine import PortfolioHealthDashboardEngine


@app.get("/portfolio-health")
def portfolio_health():
    return PortfolioHealthDashboardEngine().get_dashboard()


from app.services.tradestation_oauth_url_engine import TradeStationOAuthUrlEngine


@app.get("/tradestation-oauth-url")
def tradestation_oauth_url():
    return TradeStationOAuthUrlEngine().generate_url()


from app.services.tradestation_token_exchange_readiness_engine import TradeStationTokenExchangeReadinessEngine


@app.get("/tradestation-token-exchange-readiness")
def tradestation_token_exchange_readiness():
    return TradeStationTokenExchangeReadinessEngine().evaluate()


from app.services.tradestation_token_exchange_engine import TradeStationTokenExchangeEngine


@app.get("/tradestation-token-exchange")
def tradestation_token_exchange():
    return TradeStationTokenExchangeEngine().exchange_code()


from app.services.tradestation_token_exchange_engine import TradeStationTokenExchangeEngine


@app.get("/tradestation-token-exchange")
def tradestation_token_exchange():
    return TradeStationTokenExchangeEngine().exchange_code()


from app.services.tradestation_account_discovery_live_engine import TradeStationAccountDiscoveryLiveEngine


@app.get("/tradestation-account-discovery-live")
def tradestation_account_discovery_live():
    return TradeStationAccountDiscoveryLiveEngine().discover_accounts()


from app.services.tradestation_balance_live_engine import TradeStationBalanceLiveEngine


@app.get("/tradestation-balance-live")
def tradestation_balance_live():
    return TradeStationBalanceLiveEngine().get_balance()


from app.services.tradestation_token_refresh_engine import TradeStationTokenRefreshEngine


@app.get("/tradestation-token-refresh")
def tradestation_token_refresh():
    return TradeStationTokenRefreshEngine().refresh_access_token()


from app.services.tradestation_balance_retry_service import TradeStationBalanceRetryService


@app.get("/tradestation-balance-retry")
def tradestation_balance_retry():
    return TradeStationBalanceRetryService().get_balance_with_refresh_retry()


from app.services.tradestation_balance_retry_service import TradeStationBalanceRetryService


@app.get("/tradestation-balance-retry")
def tradestation_balance_retry():
    return TradeStationBalanceRetryService().get_balance_with_refresh_retry()


from app.services.tradestation_balance_retry_service import TradeStationBalanceRetryService


@app.get("/tradestation-balance-retry")
def tradestation_balance_retry():
    return TradeStationBalanceRetryService().get_balance_with_refresh_retry()


from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine


@app.get("/tradestation-positions-live")
def tradestation_positions_live():
    return TradeStationPositionsLiveEngine().get_positions()


from app.services.tradestation_positions_retry_service import TradeStationPositionsRetryService


@app.get("/tradestation-positions-retry")
def tradestation_positions_retry():
    return TradeStationPositionsRetryService().get_positions_with_refresh_retry()


from app.services.tradestation_orders_live_engine import TradeStationOrdersLiveEngine


@app.get("/tradestation-orders-live")
def tradestation_orders_live():
    return TradeStationOrdersLiveEngine().get_orders()


from app.services.live_portfolio_snapshot_builder import LivePortfolioSnapshotBuilder


@app.get("/live-portfolio-snapshot")
def live_portfolio_snapshot():
    return LivePortfolioSnapshotBuilder().build_snapshot()


from app.services.live_portfolio_snapshot_persistence_service import LivePortfolioSnapshotPersistenceService


@app.get("/live-portfolio-snapshot-persist")
def live_portfolio_snapshot_persist():
    return LivePortfolioSnapshotPersistenceService().save_and_verify_live_snapshot()


from app.services.live_portfolio_health_dashboard_service import LivePortfolioHealthDashboardService


@app.get("/live-portfolio-health")
def live_portfolio_health():
    return LivePortfolioHealthDashboardService().get_health_status()


from app.services.portfolio_equity_timeline_engine import PortfolioEquityTimelineEngine


@app.get("/portfolio-equity-timeline-record")
def portfolio_equity_timeline_record():
    return PortfolioEquityTimelineEngine().record_equity_point()


from app.services.portfolio_equity_timeline_reader import PortfolioEquityTimelineReader


@app.get("/portfolio-equity-timeline")
def portfolio_equity_timeline():
    return PortfolioEquityTimelineReader().read_timeline()


from app.services.portfolio_equity_timeline_reader import PortfolioEquityTimelineReader


@app.get("/portfolio-equity-timeline")
def portfolio_equity_timeline():
    return PortfolioEquityTimelineReader().read_timeline()


from app.services.portfolio_analytics_engine import PortfolioAnalyticsEngine


@app.get("/portfolio-analytics")
def portfolio_analytics():
    return PortfolioAnalyticsEngine().analyze()


from app.services.portfolio_analytics_persistence_service import PortfolioAnalyticsPersistenceService


@app.get("/portfolio-analytics-persist")
def portfolio_analytics_persist():
    return PortfolioAnalyticsPersistenceService().save_and_verify_analytics()


from app.services.portfolio_analytics_reader import PortfolioAnalyticsReader


@app.get("/portfolio-analytics-reader")
def portfolio_analytics_reader():
    return PortfolioAnalyticsReader().read_latest()


from app.services.portfolio_dashboard_service import PortfolioDashboardService


@app.get("/portfolio-dashboard")
def portfolio_dashboard():
    return PortfolioDashboardService().get_dashboard()


from app.services.portfolio_summary_engine import PortfolioSummaryEngine


@app.get("/portfolio-summary")
def portfolio_summary():
    return PortfolioSummaryEngine().get_summary()


from app.services.portfolio_alert_engine import PortfolioAlertEngine


@app.get("/portfolio-alerts")
def portfolio_alerts():
    return PortfolioAlertEngine().evaluate_alerts()


from app.services.watchlist_engine import WatchlistEngine


@app.get("/watchlist")
def watchlist():
    return WatchlistEngine().get_watchlist()


from app.services.watchlist_reader import WatchlistReader


@app.get("/watchlist-reader")
def watchlist_reader():
    return WatchlistReader().read_watchlist()


from app.services.watchlist_analytics_engine import WatchlistAnalyticsEngine


@app.get("/watchlist-analytics")
def watchlist_analytics():
    return WatchlistAnalyticsEngine().analyze_watchlist()


from app.services.watchlist_health_dashboard import WatchlistHealthDashboard


@app.get("/watchlist-health")
def watchlist_health():
    return WatchlistHealthDashboard().get_health()


from app.services.watchlist_market_scanner import WatchlistMarketScanner


@app.get("/watchlist-market-scan")
def watchlist_market_scan():
    return WatchlistMarketScanner().scan()


from app.services.market_universe_engine import MarketUniverseEngine


@app.get("/market-universe")
def market_universe():
    return MarketUniverseEngine().get_universe()


from app.services.universe_quote_scanner import UniverseQuoteScanner


@app.get("/universe-quote-scan")
def universe_quote_scan():
    return UniverseQuoteScanner().scan_universe()


from app.services.live_universe_quote_scanner import LiveUniverseQuoteScanner


@app.get("/live-universe-quote-scan")
def live_universe_quote_scan():
    return LiveUniverseQuoteScanner().scan_safe_subset()


from app.services.opportunity_scoring_engine import OpportunityScoringEngine


@app.get("/opportunity-scores")
def opportunity_scores():
    return OpportunityScoringEngine().score_opportunities()


from app.services.liquidity_scoring_engine import LiquidityScoringEngine


@app.get("/liquidity-score-nvda")
def liquidity_score_nvda():
    return LiquidityScoringEngine().score_symbol("NVDA")


from app.services.setup_scoring_engine import SetupScoringEngine


@app.get("/setup-score-nvda")
def setup_score_nvda():
    return SetupScoringEngine().score_symbol("NVDA")


from app.services.execution_governor import ExecutionGovernor


@app.get("/execution-governor-execute")
def execution_governor_execute():
    return ExecutionGovernor().evaluate_execution_permission("EXECUTE")


from app.services.opportunity_summary_engine import OpportunitySummaryEngine


@app.get("/opportunity-summary")
def opportunity_summary():
    return OpportunitySummaryEngine().get_summary()


from app.services.regime_scoring_engine import RegimeScoringEngine


@app.get("/regime-score-nvda")
def regime_score_nvda():
    return RegimeScoringEngine().score_symbol("NVDA")


from app.services.volatility_scoring_engine import VolatilityScoringEngine


@app.get("/volatility-score-nvda")
def volatility_score_nvda():
    return VolatilityScoringEngine().score_symbol("NVDA")


from app.services.expected_value_scoring_engine import ExpectedValueScoringEngine


@app.get("/expected-value-score-nvda")
def expected_value_score_nvda():
    return ExpectedValueScoringEngine().score_symbol("NVDA")


from app.services.trend_persistence_scoring_engine import TrendPersistenceScoringEngine


@app.get("/trend-persistence-score-nvda")
def trend_persistence_score_nvda():
    return TrendPersistenceScoringEngine().score_symbol("NVDA")

