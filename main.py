from app.routes import portfolio_governor
from fastapi import FastAPI
from app.routes.historical_data_import import router as historical_data_import_router
from app.routes.simulation_outcomes import router as simulation_outcomes_router
from app.routes.simulation_report import router as simulation_report_router
from app.routes.simulation_ledger import router as simulation_ledger_router
from app.routes.walk_forward_simulation import router as walk_forward_simulation_router
from app.routes.institutional_flow import router as institutional_flow_router
from app.routes import ai_operator
from app.routes import paper_trade_ledger
from app.routes import paper_account_dashboard_route
from app.routes import options_account_dashboard
from app.routes import paper_trade_executor
from app.routes import core
from app.routes import paper_trading
from app.routes import tradestation
from app.routes import portfolio
from app.routes import watchlist
from app.routes import market_intelligence
from app.routes import institutional_flow
from app.routes import leadership
from app.routes import backend_admin
from app.routes import broker_readiness
from app.routes import decision_performance
from app.routes import decision_outcomes
from app.routes import decision_self_audit

app = FastAPI(title="GreyLine Backend Server")
app.include_router(historical_data_import_router)
app.include_router(simulation_outcomes_router)
app.include_router(simulation_report_router)
app.include_router(simulation_ledger_router)
app.include_router(walk_forward_simulation_router)
app.include_router(institutional_flow_router)
app.include_router(core.router)
app.include_router(paper_trading.router)
app.include_router(tradestation.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(market_intelligence.router)
app.include_router(institutional_flow.router)
app.include_router(leadership.router)
app.include_router(backend_admin.router)
app.include_router(broker_readiness.router)
app.include_router(decision_performance.router)
app.include_router(decision_outcomes.router)
app.include_router(decision_self_audit.router)

from app.routes import decision_metrics

app.include_router(decision_metrics.router)

from app.routes import operator_decision_dashboard

app.include_router(operator_decision_dashboard.router)

from app.routes import decision_scheduler

app.include_router(decision_scheduler.router)

from app.routes import decision_validation

app.include_router(decision_validation.router)

from app.routes import forward_outcomes

app.include_router(forward_outcomes.router)

from app.routes import tradestation_token_maintenance

app.include_router(tradestation_token_maintenance.router)

from app.routes import tradestation_auth_exchange

app.include_router(tradestation_auth_exchange.router)

from app.routes import tradestation_auth_url

app.include_router(tradestation_auth_url.router)

from app.routes import decision_outcome_scores

app.include_router(decision_outcome_scores.router)

from app.routes import decision_accuracy_dashboard

app.include_router(decision_accuracy_dashboard.router)

from app.routes import decision_learning

app.include_router(decision_learning.router)

from app.routes import decision_learning_memory

app.include_router(decision_learning_memory.router)

from app.routes import learning_analytics

app.include_router(learning_analytics.router)

from app.routes import decision_feature_attribution

app.include_router(decision_feature_attribution.router)

from app.routes import decision_weight_recommendations

app.include_router(decision_weight_recommendations.router)

from app.routes import adaptive_weight_governance

app.include_router(adaptive_weight_governance.router)

from app.routes import system_health

app.include_router(system_health.router)

from app.routes import startup_recovery

app.include_router(startup_recovery.router)

from app.routes import background_scheduler

app.include_router(background_scheduler.router)

from app.routes import audit_ledger

app.include_router(audit_ledger.router)

from app.services.background_scheduler_service import BackgroundSchedulerService

@app.on_event("startup")
def auto_start_background_scheduler():
    BackgroundSchedulerService.start()

from app.routes import greyline_connection_watchdog
app.include_router(greyline_connection_watchdog.router)

from app.routes import pre_trade_risk_gate
app.include_router(pre_trade_risk_gate.router)

from app.routes import live_trade_authority_gate
from app.routes import deployment_governance
from app.routes import paper_trade_history
app.include_router(live_trade_authority_gate.router)

app.include_router(ai_operator.router)
app.include_router(paper_trade_ledger.router)
app.include_router(paper_account_dashboard_route.router)
app.include_router(options_account_dashboard.router)
app.include_router(paper_trade_executor.router)

app.include_router(deployment_governance.router)

app.include_router(paper_trade_history.router)

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request

templates = Jinja2Templates(directory="app/templates")

@app.get("/operator-dashboard", response_class=HTMLResponse)
async def operator_dashboard(request: Request):
    return templates.TemplateResponse("operator_dashboard.html", {"request": request})

from app.routes import greyline_reliability_core
app.include_router(greyline_reliability_core.router)

from app.routes import fast_quote_heartbeat
app.include_router(fast_quote_heartbeat.router)

from app.services.fast_quote_heartbeat_service import FastQuoteHeartbeatService

@app.on_event("startup")
def auto_start_fast_quote_heartbeat():
    FastQuoteHeartbeatService.start(
        symbols=["AMD", "NVDA"],
        interval_market_open_seconds=5,
        interval_market_closed_seconds=300,
    )

from app.routes import opportunity_balance
app.include_router(opportunity_balance.router)

from app.routes import directional_opportunity_report
from app.routes import directional_attribution_report
app.include_router(directional_opportunity_report.router)
app.include_router(directional_attribution_report.router)

from app.routes import directional_readiness_dashboard
app.include_router(directional_readiness_dashboard.router)

from app.routes import flow_feed_readiness_report
app.include_router(flow_feed_readiness_report.router)

from app.routes import greyline_market_battlefield
app.include_router(greyline_market_battlefield.router)

from app.routes import greyline_market_battlefield_summary
app.include_router(greyline_market_battlefield_summary.router)

from app.routes import market_battlefield_cache
app.include_router(market_battlefield_cache.router)

from app.routes import options_trade_forensics
app.include_router(options_trade_forensics.router)

from app.routes import market_battlefield_forecast
app.include_router(market_battlefield_forecast.router)

from app.routes import battlefield_learning
from app.routes import forecast_accuracy_dashboard
from app.routes import forecast_reliability_dashboard
app.include_router(battlefield_learning.router)
app.include_router(forecast_accuracy_dashboard.router)
app.include_router(forecast_reliability_dashboard.router)

app.include_router(portfolio_governor.router)

from app.services.position_alert_ack_engine import PositionAlertAckEngine

@app.get("/position-alerts")
def position_alerts():
    return PositionAlertAckEngine().unacknowledged_alerts()

@app.post("/position-alerts/ack/{trade_id}")
def acknowledge_position_alert(trade_id: str):
    return PositionAlertAckEngine().acknowledge(trade_id)

from app.services.operator_notification_engine import OperatorNotificationEngine

@app.get("/operator-notifications")
def operator_notifications():
    return OperatorNotificationEngine().unread()

@app.post("/operator-notifications/ack/{notification_id}")
def acknowledge_operator_notification(notification_id: str):
    return OperatorNotificationEngine().acknowledge(notification_id)

from app.services.operator_event_bus_engine import OperatorEventBusEngine

@app.get("/operator-events")
def operator_events():
    return OperatorEventBusEngine().recent()

@app.post("/operator-events/test")
def operator_events_test():
    return OperatorEventBusEngine().publish(
        source="MANUAL_TEST",
        category="SYSTEM_TEST",
        severity="WARNING",
        title="Operator Event Bus Test",
        message="Manual operator event bus test notification.",
        ack_required=True,
        payload={"test": True},
    )
