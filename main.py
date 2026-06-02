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
