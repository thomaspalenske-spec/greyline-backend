from fastapi import APIRouter

from app.services.ledger_engine import LedgerEngine
from app.services.snapshot_engine import SnapshotEngine
from app.services.account_engine import AccountEngine
from app.services.position_reconciliation_engine import PositionReconciliationEngine
from app.services.system_status_engine import SystemStatusEngine
from app.services.backend_readiness_engine import BackendReadinessEngine
from app.services.backend_manifest_engine import BackendManifestEngine
from app.services.runtime_configuration_engine import RuntimeConfigurationEngine
from app.services.runtime_safety_summary_engine import RuntimeSafetySummaryEngine
from app.services.deployment_mode_gate_engine import DeploymentModeGateEngine
from app.services.configuration_validation_engine import ConfigurationValidationEngine
from app.services.account_drift_detector_engine import AccountDriftDetectorEngine
from app.services.account_health_engine import AccountHealthEngine
from app.services.audit_log_engine import AuditLogEngine
from app.services.backend_capability_registry_engine import BackendCapabilityRegistryEngine
from app.services.backend_control_center_engine import BackendControlCenterEngine
from app.services.backend_phase_gate_engine import BackendPhaseGateEngine
from app.services.backend_ucf_registry_engine import BackendUcfRegistryEngine
from app.services.restore_engine import RestoreEngine

router = APIRouter()


@router.get("/ledger")
def ledger():
    return LedgerEngine().load()


@router.get("/snapshot")
def snapshot():
    return SnapshotEngine().create_snapshot({"system": "GreyLine", "snapshot_test": True})


@router.get("/account")
def account():
    return AccountEngine().get_account_status()


@router.get("/reconcile")
def reconcile():
    return PositionReconciliationEngine().reconcile_positions()


@router.get("/system-status")
def system_status():
    return SystemStatusEngine().get_status()


@router.get("/backend-readiness")
def backend_readiness():
    return BackendReadinessEngine().evaluate_readiness(
        api_online=True,
        ledger_online=True,
        snapshot_online=True,
        reconciliation_online=True,
        account_health="HEALTHY"
    )


@router.get("/manifest")
def manifest():
    return BackendManifestEngine().get_manifest()


@router.get("/runtime-configuration")
def runtime_configuration():
    return RuntimeConfigurationEngine().get_runtime_configuration()


@router.get("/runtime-safety")
def runtime_safety():
    return RuntimeSafetySummaryEngine().summarize_runtime_safety(
        broker_connected=False,
        autonomous_execution_enabled=False,
        authority_level="OBSERVE_RECOMMEND_ONLY",
        kill_switch_status="STANDBY",
        credential_safety_approved=True
    )


@router.get("/deployment-mode-gate")
def deployment_mode_gate():
    return DeploymentModeGateEngine().evaluate_mode(requested_mode="PAPER_TRADING_PREP")


@router.get("/configuration-validation")
def configuration_validation():
    return ConfigurationValidationEngine().validate_configuration(
        {
            "GREYLINE_MODE": "LOCAL_DEVELOPMENT",
            "GREYLINE_ENVIRONMENT": "MacBook",
            "BROKER_CONNECTION_ENABLED": False,
            "AUTONOMOUS_EXECUTION_ENABLED": False
        }
    )


@router.get("/account-drift")
def account_drift():
    return AccountDriftDetectorEngine().detect_drift(ledger_equity=10000, reported_equity=10000)


@router.get("/account-health")
def account_health():
    return AccountHealthEngine().evaluate_health(
        reconciliation_status="PASS",
        drift_detected=False,
        snapshot_valid=True
    )


@router.get("/audit-log")
def audit_log():
    return AuditLogEngine().create_log(
        action="AUDIT_TEST",
        status="PASS",
        details={"system": "GreyLine"}
    )


@router.get("/backend-capabilities")
def backend_capabilities():
    return BackendCapabilityRegistryEngine().list_capabilities()


@router.get("/backend-control-center")
def backend_control_center():
    return BackendControlCenterEngine().get_control_center()


@router.get("/backend-phase-gate")
def backend_phase_gate():
    return BackendPhaseGateEngine().evaluate_phase_gate(
        backend_ready=True,
        control_center_online=True,
        ucf_registry_active=True,
        capability_registry_active=True,
        milestone_registry_active=True
    )


@router.get("/backend-ucfs")
def backend_ucfs():
    return BackendUcfRegistryEngine().list_ucfs()


@router.get("/restore")
def restore():
    return RestoreEngine().restore_snapshot("app/snapshots/snapshot_20260530_131732.json")
