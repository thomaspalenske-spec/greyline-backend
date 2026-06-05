from fastapi import FastAPI
from app.routes import core
from app.routes import paper_trading
from app.routes import tradestation
from app.routes import portfolio
from app.routes import watchlist
from app.routes import market_intelligence
from app.routes import institutional_flow
from app.routes import leadership
from app.routes import backend_admin

app = FastAPI(title="GreyLine Backend Server")
app.include_router(core.router)
app.include_router(paper_trading.router)
app.include_router(tradestation.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(market_intelligence.router)
app.include_router(institutional_flow.router)
app.include_router(leadership.router)
app.include_router(backend_admin.router)
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


