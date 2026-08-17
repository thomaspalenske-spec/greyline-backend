from fastapi import APIRouter

from app.services.credential_safety_gate_engine import CredentialSafetyGateEngine
from app.services.credential_storage_policy_engine import CredentialStoragePolicyEngine
from app.services.environment_file_guard_engine import EnvironmentFileGuardEngine
from app.services.broker_safety_summary_engine import BrokerSafetySummaryEngine
from app.services.broker_sandbox_connection_plan_engine import BrokerSandboxConnectionPlanEngine
from app.services.tradestation_readiness_checklist_engine import TradeStationReadinessChecklistEngine
from app.services.tradestation_sandbox_readiness_engine import TradeStationSandboxReadinessEngine
from app.services.tradestation_credential_validation_engine import TradeStationCredentialValidationEngine
from app.services.api_credential_readiness_engine import ApiCredentialReadinessEngine
from app.services.broker_integration_readiness_engine import BrokerIntegrationReadinessEngine
from app.services.broker_integration_blocker_engine import BrokerIntegrationBlockerEngine

router = APIRouter()


@router.get("/credential-safety-gate")
def credential_safety_gate():
    # Derive env_file_present / gitignore_protects_env from the guard engine's REAL file reads instead
    # of asserting True — a broken .gitignore rule must fail this gate, not sail through green.
    guard = EnvironmentFileGuardEngine().evaluate_environment_guard()
    return CredentialSafetyGateEngine().evaluate_credential_safety(
        credentials_in_plaintext=False,
        env_file_present=bool(guard.get("env_file_present")),
        gitignore_protects_env=bool(guard.get("gitignore_protects_env")),
        credential_rotation_required=False
    )


@router.get("/credential-storage-policy")
def credential_storage_policy():
    return CredentialStoragePolicyEngine().get_policy()


@router.get("/environment-file-guard")
def environment_file_guard():
    return EnvironmentFileGuardEngine().evaluate_environment_guard()


@router.get("/broker-safety-summary")
def broker_safety_summary():
    # Derive the execution-state inputs from the REAL execution governor + kill-switch env, not
    # hardcoded literals — asserting execution_blocked=False / trading_allowed=False while the actual
    # governor said otherwise would render a false safety verdict.
    from os import getenv
    from app.services.execution_governor import ExecutionGovernor
    perm = ExecutionGovernor().evaluate_execution_permission("EXECUTE")
    return BrokerSafetySummaryEngine().summarize_safety(
        safe_for_broker_prep=True,
        authority_approved=True,
        execution_blocked=not bool(perm.get("execution_enabled")),
        kill_switch_status=getenv("GREYLINE_KILL_SWITCH_STATE", "LOCKED").upper(),
        trading_allowed=bool(perm.get("order_placement_allowed"))
    )


@router.get("/broker-sandbox-plan")
def broker_sandbox_plan():
    return BrokerSandboxConnectionPlanEngine().get_plan()


@router.get("/tradestation-readiness")
def tradestation_readiness():
    return TradeStationReadinessChecklistEngine().evaluate_checklist()


@router.get("/tradestation-sandbox-readiness")
def tradestation_sandbox_readiness():
    return TradeStationSandboxReadinessEngine().evaluate()


@router.get("/tradestation-credential-validation")
def tradestation_credential_validation():
    return TradeStationCredentialValidationEngine().evaluate()


@router.get("/api-credential-readiness")
def api_credential_readiness():
    return ApiCredentialReadinessEngine().evaluate_credentials()


@router.get("/broker-integration-readiness")
def broker_integration_readiness():
    # autonomous_execution_enabled is the safety-critical input — derive it from the REAL execution
    # governor rather than asserting False, so an actually-enabled execution state can't hide behind a
    # hardcoded "off". (The other flags are always-on architectural subsystems.)
    from app.services.execution_governor import ExecutionGovernor
    perm = ExecutionGovernor().evaluate_execution_permission("EXECUTE")
    return BrokerIntegrationReadinessEngine().evaluate_readiness(
        ledger_supremacy_active=True,
        audit_log_active=True,
        snapshot_restore_active=True,
        reconciliation_active=True,
        drift_detection_active=True,
        autonomous_execution_enabled=bool(perm.get("execution_enabled"))
    )


@router.get("/broker-integration-blockers")
def broker_integration_blockers():
    return BrokerIntegrationBlockerEngine().evaluate_blockers()
