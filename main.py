from fastapi import FastAPI
from app.routes import core
from app.routes import paper_trading
from app.routes import tradestation
from app.routes import portfolio
from app.routes import watchlist
from app.routes import market_intelligence
from app.routes import institutional_flow
from app.routes import leadership

app = FastAPI(title="GreyLine Backend Server")
app.include_router(core.router)
app.include_router(paper_trading.router)
app.include_router(tradestation.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(market_intelligence.router)
app.include_router(institutional_flow.router)
app.include_router(leadership.router)
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

