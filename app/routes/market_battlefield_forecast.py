from fastapi import APIRouter
from app.routes.greyline_market_battlefield_summary import greyline_market_battlefield_summary
from app.services.battlefield_forecast_engine import BattlefieldForecastEngine
from app.services.battlefield_history_engine import BattlefieldHistoryEngine
from app.services.battlefield_trend_engine import BattlefieldTrendEngine
from app.services.battlefield_momentum_engine import BattlefieldMomentumEngine

router = APIRouter()


@router.get("/market-battlefield-forecast")
def market_battlefield_forecast():
    battlefield = greyline_market_battlefield_summary()
    history_engine = BattlefieldHistoryEngine()
    history_record = history_engine.record(battlefield)
    recent_history = history_engine.history(limit=50)
    trend = BattlefieldTrendEngine().evaluate(recent_history)
    momentum = BattlefieldMomentumEngine().evaluate(recent_history)
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
        "forecast": forecast,
        "status": "MARKET_BATTLEFIELD_FORECAST_READY",
    }
