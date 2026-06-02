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
    return SnapshotEngine().create_snapshot()


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
    return CredentialSafetyGateEngine().evaluate_gate(
        credential_storage_approved=True,
        secrets_redacted=True,
        environment_file_protected=True
    )


@app.get("/credential-storage-policy")
def credential_storage_policy():
    return CredentialStoragePolicyEngine().get_policy()


@app.get("/environment-file-guard")
def environment_file_guard():
    return EnvironmentFileGuardEngine().evaluate_environment_file(
        gitignore_protected=True,
        source_control_safe=True
    )


@app.get("/broker-safety-summary")
def broker_safety_summary():
    return BrokerSafetySummaryEngine().summarize_safety(
        broker_connected=False,
        execution_enabled=False,
        authority_level="OBSERVE_RECOMMEND_ONLY"
    )


@app.get("/broker-sandbox-plan")
def broker_sandbox_plan():
    return BrokerSandboxConnectionPlanEngine().get_plan()
