from fastapi import FastAPI

from app.services.account_engine import AccountEngine
from app.services.ledger_engine import LedgerEngine
from app.services.snapshot_engine import SnapshotEngine
from app.services.position_reconciliation_engine import PositionReconciliationEngine
from app.services.schema_validator import SchemaValidator

app = FastAPI(title="GreyLine Backend")


@app.get("/")
def home():
    return {
        "system": "GreyLine",
        "status": "ONLINE"
    }


@app.get("/account")
def account():
    engine = AccountEngine()
    return engine.get_account_status()


@app.get("/ledger")
def ledger():
    engine = LedgerEngine()
    return engine.load()


@app.get("/snapshot")
def snapshot():
    engine = SnapshotEngine()
    return engine.create_snapshot()


@app.get("/reconcile")
def reconcile():
    engine = PositionReconciliationEngine()
    return engine.reconcile_positions()


@app.get("/validate-test")
def validate_test():
    validator = SchemaValidator()

    test_trade = {
        "symbol": "NVDA",
        "quantity": 1,
        "entry_price": 215.33,
        "state": "ACTIVE"
    }

    return validator.validate_trade(test_trade)
from app.services.trade_id_engine import TradeIdEngine


@app.get("/trade-id-test")
def trade_id_test():

    engine = TradeIdEngine()

    existing_trades = [
        {"symbol": "NVDA"},
        {"symbol": "MSFT"},
        {"symbol": "AVGO"}
    ]

    return {
        "trade_id": engine.generate_trade_id(existing_trades)
    }

from app.services.audit_log_engine import AuditLogEngine


@app.get("/audit-test")
def audit_test():
    engine = AuditLogEngine()

    return engine.create_log(
        action="MILESTONE_TEST",
        status="PASS",
        details={
            "milestone": "Audit Log Engine",
            "system": "GreyLine"
        }
    )


from app.services.snapshot_integrity_engine import SnapshotIntegrityEngine


@app.get("/snapshot-integrity-test")
def snapshot_integrity_test():
    engine = SnapshotIntegrityEngine()

    return engine.validate_snapshot(
        "app/snapshots/snapshot_20260530_131732.json"
    )


from app.services.restore_engine import RestoreEngine


@app.get("/restore-test")
def restore_test():
    engine = RestoreEngine()

    return engine.restore_snapshot(
        "app/snapshots/snapshot_20260530_131732.json"
    )


from app.services.snapshot_registry_engine import SnapshotRegistryEngine


@app.get("/snapshots")
def snapshots():
    engine = SnapshotRegistryEngine()

    return {
        "snapshots": engine.list_snapshots()
    }


from app.services.reconciliation_validator_engine import ReconciliationValidatorEngine


@app.get("/reconciliation-validator-test")
def reconciliation_validator_test():
    engine = ReconciliationValidatorEngine()

    ledger_positions = [
        {"symbol": "NVDA"},
        {"symbol": "MSFT"},
        {"symbol": "AVGO"}
    ]

    active_positions = [
        {"symbol": "NVDA"},
        {"symbol": "MSFT"},
        {"symbol": "AVGO"}
    ]

    return engine.validate(ledger_positions, active_positions)


from app.services.reconciliation_report_engine import ReconciliationReportEngine


@app.get("/reconciliation-report-test")
def reconciliation_report_test():
    engine = ReconciliationReportEngine()

    ledger_positions = [
        {"symbol": "NVDA"},
        {"symbol": "MSFT"},
        {"symbol": "AVGO"}
    ]

    active_positions = [
        {"symbol": "NVDA"},
        {"symbol": "MSFT"},
        {"symbol": "AVGO"}
    ]

    return engine.generate_report(
        ledger_positions,
        active_positions
    )
from app.services.account_drift_detector_engine import AccountDriftDetectorEngine


@app.get("/account-drift-test")
def account_drift_test():
    engine = AccountDriftDetectorEngine()

    return engine.detect_drift(
        ledger_equity=10000,
        reported_equity=10000
    )


from app.services.account_drift_detector_engine import AccountDriftDetectorEngine


@app.get("/account-drift-test")
def account_drift_test():
    engine = AccountDriftDetectorEngine()

    return engine.detect_drift(
        ledger_equity=10000,
        reported_equity=10000
    )
from app.services.account_health_engine import AccountHealthEngine


@app.get("/account-health-test")
def account_health_test():
    engine = AccountHealthEngine()

    return engine.evaluate_health(
        reconciliation_status="PASS",
        drift_detected=False,
        snapshot_valid=True
    )
from app.services.system_status_engine import SystemStatusEngine


@app.get("/system-status")
def system_status():
    engine = SystemStatusEngine()
    return engine.get_status()
from app.services.backend_readiness_engine import BackendReadinessEngine


@app.get("/backend-readiness")
def backend_readiness():
    engine = BackendReadinessEngine()

    return engine.evaluate_readiness(
        api_online=True,
        ledger_online=True,
        snapshot_online=True,
        reconciliation_online=True,
        account_health="HEALTHY"
    )
from app.services.milestone_registry_engine import MilestoneRegistryEngine


@app.get("/milestones")
def milestones():
    engine = MilestoneRegistryEngine()
    return engine.list_milestones()
from app.services.backend_manifest_engine import BackendManifestEngine


@app.get("/manifest")
def manifest():
    engine = BackendManifestEngine()
    return engine.get_manifest()
from app.services.backend_capability_registry_engine import BackendCapabilityRegistryEngine


@app.get("/capabilities")
def capabilities():
    engine = BackendCapabilityRegistryEngine()
    return engine.list_capabilities()
from app.services.backend_ucf_registry_engine import BackendUcfRegistryEngine


@app.get("/ucfs")
def ucfs():
    engine = BackendUcfRegistryEngine()
    return engine.list_ucfs()
from app.services.backend_control_center_engine import BackendControlCenterEngine


@app.get("/control-center")
def control_center():
    engine = BackendControlCenterEngine()
    return engine.get_control_center()
from app.services.backend_phase_gate_engine import BackendPhaseGateEngine


@app.get("/phase-gate")
def phase_gate():
    engine = BackendPhaseGateEngine()

    return engine.evaluate_phase_gate(
        backend_ready=True,
        control_center_online=True,
        ucf_registry_active=True,
        capability_registry_active=True,
        milestone_registry_active=True
    )
from app.services.broker_integration_readiness_engine import BrokerIntegrationReadinessEngine


@app.get("/broker-readiness")
def broker_readiness():
    engine = BrokerIntegrationReadinessEngine()

    return engine.evaluate_readiness(
        ledger_supremacy_active=True,
        audit_log_active=True,
        snapshot_restore_active=True,
        reconciliation_active=True,
        drift_detection_active=True,
        autonomous_execution_enabled=False
    )
from app.services.tradestation_readiness_checklist_engine import TradeStationReadinessChecklistEngine


@app.get("/tradestation-readiness")
def tradestation_readiness():
    engine = TradeStationReadinessChecklistEngine()
    return engine.evaluate_checklist()
from app.services.broker_authority_gate_engine import BrokerAuthorityGateEngine


@app.get("/broker-authority-gate")
def broker_authority_gate():
    engine = BrokerAuthorityGateEngine()

    return engine.evaluate_authority(
        requested_authority_level="OBSERVE_RECOMMEND_ONLY"
    )
from app.services.broker_kill_switch_engine import BrokerKillSwitchEngine


@app.get("/broker-kill-switch")
def broker_kill_switch():
    engine = BrokerKillSwitchEngine()

    return engine.evaluate_kill_switch(
        emergency_stop_active=False,
        broker_connected=False,
        autonomous_execution_enabled=False
    )
from app.services.broker_safety_summary_engine import BrokerSafetySummaryEngine


@app.get("/broker-safety-summary")
def broker_safety_summary():
    engine = BrokerSafetySummaryEngine()

    return engine.summarize_safety(
        safe_for_broker_prep=True,
        authority_approved=True,
        execution_blocked=False,
        kill_switch_status="STANDBY",
        trading_allowed=False
    )
from app.services.broker_integration_blocker_engine import BrokerIntegrationBlockerEngine


@app.get("/broker-blockers")
def broker_blockers():
    engine = BrokerIntegrationBlockerEngine()
    return engine.evaluate_blockers()
from app.services.broker_prep_roadmap_engine import BrokerPrepRoadmapEngine


@app.get("/broker-roadmap")
def broker_roadmap():
    engine = BrokerPrepRoadmapEngine()
    return engine.get_roadmap()
from app.services.paper_trading_readiness_engine import PaperTradingReadinessEngine


@app.get("/paper-trading-readiness")
def paper_trading_readiness():
    engine = PaperTradingReadinessEngine()
    return engine.evaluate_readiness()
from app.services.api_credential_readiness_engine import ApiCredentialReadinessEngine


@app.get("/api-credential-readiness")
def api_credential_readiness():
    engine = ApiCredentialReadinessEngine()
    return engine.evaluate_credentials()
from app.services.credential_safety_gate_engine import CredentialSafetyGateEngine


@app.get("/credential-safety")
def credential_safety():
    engine = CredentialSafetyGateEngine()

    return engine.evaluate_credential_safety(
        credentials_in_plaintext=False,
        env_file_present=True,
        gitignore_protects_env=True,
        credential_rotation_required=False
    )
from app.services.environment_file_guard_engine import EnvironmentFileGuardEngine


@app.get("/environment-guard")
def environment_guard():
    engine = EnvironmentFileGuardEngine()
    return engine.evaluate_environment_guard()
from app.services.credential_storage_policy_engine import CredentialStoragePolicyEngine


@app.get("/credential-storage-policy")
def credential_storage_policy():
    engine = CredentialStoragePolicyEngine()
    return engine.get_policy()
from app.services.configuration_validation_engine import ConfigurationValidationEngine


@app.get("/configuration-validation")
def configuration_validation():
    engine = ConfigurationValidationEngine()

    return engine.validate_configuration(
        {
            "GREYLINE_MODE": "LOCAL_DEVELOPMENT",
            "GREYLINE_ENVIRONMENT": "MacBook",
            "BROKER_CONNECTION_ENABLED": False,
            "AUTONOMOUS_EXECUTION_ENABLED": False
        }
    )
from app.services.runtime_configuration_engine import RuntimeConfigurationEngine


@app.get("/runtime-configuration")
def runtime_configuration():
    engine = RuntimeConfigurationEngine()
    return engine.get_runtime_configuration()
from app.services.runtime_safety_summary_engine import RuntimeSafetySummaryEngine


@app.get("/runtime-safety")
def runtime_safety():
    engine = RuntimeSafetySummaryEngine()

    return engine.summarize_runtime_safety(
        broker_connected=False,
        autonomous_execution_enabled=False,
        authority_level="OBSERVE_RECOMMEND_ONLY",
        kill_switch_status="STANDBY",
        credential_safety_approved=True
    )
from app.services.deployment_mode_gate_engine import DeploymentModeGateEngine


@app.get("/deployment-mode-gate")
def deployment_mode_gate():
    engine = DeploymentModeGateEngine()

    return engine.evaluate_mode(
        requested_mode="PAPER_TRADING_PREP"
    )
from app.services.paper_trading_prep_gate_engine import PaperTradingPrepGateEngine


@app.get("/paper-trading-prep-gate")
def paper_trading_prep_gate():
    engine = PaperTradingPrepGateEngine()

    return engine.evaluate_prep_gate(
        backend_ready=True,
        broker_safety_ready=True,
        credential_safety_ready=True,
        authority_gate_ready=True,
        kill_switch_ready=True
    )
from app.services.paper_trading_blocker_engine import PaperTradingBlockerEngine


@app.get("/paper-trading-blockers")
def paper_trading_blockers():
    engine = PaperTradingBlockerEngine()
    return engine.evaluate_blockers()
