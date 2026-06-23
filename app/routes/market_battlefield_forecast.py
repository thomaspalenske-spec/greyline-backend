from fastapi import APIRouter
from app.routes.greyline_market_battlefield_summary import greyline_market_battlefield_summary
from app.services.battlefield_forecast_engine import BattlefieldForecastEngine
from app.services.battlefield_history_engine import BattlefieldHistoryEngine
from app.services.battlefield_trend_engine import BattlefieldTrendEngine
from app.services.battlefield_momentum_engine import BattlefieldMomentumEngine
from app.services.battlefield_transition_engine import BattlefieldTransitionEngine
from app.services.opportunity_queue_engine import OpportunityQueueEngine
from app.services.opportunity_escalation_engine import OpportunityEscalationEngine
from app.services.battlefield_readiness_timer_engine import BattlefieldReadinessTimerEngine

router = APIRouter()


@router.get("/market-battlefield-forecast")
def market_battlefield_forecast():
    battlefield = greyline_market_battlefield_summary()
    history_engine = BattlefieldHistoryEngine()
    history_record = history_engine.record(battlefield)
    recent_history = history_engine.history(limit=50)
    trend = BattlefieldTrendEngine().evaluate(recent_history)
    momentum = BattlefieldMomentumEngine().evaluate(recent_history)
    transition = BattlefieldTransitionEngine().evaluate(recent_history)
    opportunity_queue = OpportunityQueueEngine().build(battlefield)
    opportunity_escalation = OpportunityEscalationEngine().evaluate(opportunity_queue)
    readiness_timer = BattlefieldReadinessTimerEngine().evaluate(opportunity_queue)
    forecast = BattlefieldForecastEngine().forecast(battlefield)

    return {
        "system": "GreyLine",
        "engine": "MarketBattlefieldForecastRoute",
        "battlefield_cache": battlefield.get("snapshot_cache", {}),
        "current_battlefield_health": battlefield.get("battlefield_health"),
        "battlefield_health_reason": battlefield.get("battlefield_health_reason"),
        "history_record": history_record,
        "trend": trend,
        "momentum": momentum,
        "transition": transition,
        "opportunity_queue": opportunity_queue,
        "opportunity_escalation": opportunity_escalation,
        "readiness_timer": readiness_timer,
        "forecast": forecast,
        "status": "MARKET_BATTLEFIELD_FORECAST_READY",
    }
