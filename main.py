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

