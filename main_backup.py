from fastapi import FastAPI
from app.routes.greyline_reliability_core import router as greyline_reliability_core_router
from app.routes.position_alerts import router as position_alerts_router

from app.services.account_engine import AccountEngine
from app.services.ledger_engine import LedgerEngine
from app.services.snapshot_engine import SnapshotEngine
from app.services.position_reconciliation_engine import PositionReconciliationEngine
from app.services.schema_validator import SchemaValidator


from app.routes.background_scheduler import router as background_scheduler_router
from app.routes.operator_commander_summary import router as operator_commander_summary_router
from app.routes.greyline_market_battlefield_summary import router as greyline_market_battlefield_summary_router
from app.routes.options_account_dashboard import router as options_account_dashboard_router


from app.routes.tradestation import router as tradestation_router
from app.routes.operator_cockpit_status import router as operator_cockpit_status_router
from app.routes.fast_quote_heartbeat import router as fast_quote_heartbeat_router
from app.routes.system_health import router as system_health_router

app = FastAPI(title="GreyLine Backend")
app.include_router(greyline_reliability_core_router)
app.include_router(position_alerts_router)

app.include_router(tradestation_router)
app.include_router(operator_cockpit_status_router)
app.include_router(fast_quote_heartbeat_router)
app.include_router(system_health_router)


app.include_router(background_scheduler_router)
app.include_router(operator_commander_summary_router)
app.include_router(greyline_market_battlefield_summary_router)
app.include_router(options_account_dashboard_router)



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
