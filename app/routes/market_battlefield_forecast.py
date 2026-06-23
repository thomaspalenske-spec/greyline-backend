from fastapi import APIRouter
import traceback
from app.routes.greyline_market_battlefield_summary import greyline_market_battlefield_summary
from app.services.battlefield_forecast_engine import BattlefieldForecastEngine
from app.services.battlefield_history_engine import BattlefieldHistoryEngine
from app.services.battlefield_trend_engine import BattlefieldTrendEngine
from app.services.battlefield_momentum_engine import BattlefieldMomentumEngine
from app.services.battlefield_transition_engine import BattlefieldTransitionEngine
from app.services.opportunity_queue_engine import OpportunityQueueEngine
from app.services.opportunity_escalation_engine import OpportunityEscalationEngine
from app.services.battlefield_readiness_timer_engine import BattlefieldReadinessTimerEngine
from app.services.readiness_acceleration_engine import ReadinessAccelerationEngine
from app.services.why_not_ready_engine import WhyNotReadyEngine
from app.services.opportunity_funnel_engine import OpportunityFunnelEngine
from app.services.candidate_rejection_summary_engine import CandidateRejectionSummaryEngine
from app.services.readiness_heatmap_engine import ReadinessHeatmapEngine
from app.services.opportunity_autopsy_engine import OpportunityAutopsyEngine
from app.services.opportunity_outcome_tracker_engine import OpportunityOutcomeTrackerEngine
from app.services.forward_outcome_analyzer_engine import ForwardOutcomeAnalyzerEngine

router = APIRouter()


@router.get("/market-battlefield-forecast")
def market_battlefield_forecast():
    try:
        battlefield = greyline_market_battlefield_summary(force_refresh=True)
        history_engine = BattlefieldHistoryEngine()
        history_record = history_engine.record(battlefield)
        recent_history = history_engine.history(limit=50)
        trend = BattlefieldTrendEngine().evaluate(recent_history)
        momentum = BattlefieldMomentumEngine().evaluate(recent_history)
        transition = BattlefieldTransitionEngine().evaluate(recent_history)
        opportunity_queue = OpportunityQueueEngine().build(battlefield)
        opportunity_escalation = OpportunityEscalationEngine().evaluate(opportunity_queue)
        readiness_timer = BattlefieldReadinessTimerEngine().evaluate(opportunity_queue)
        why_not_ready = WhyNotReadyEngine().evaluate(opportunity_queue)
        opportunity_funnel = OpportunityFunnelEngine().evaluate(opportunity_queue.get('queue', []))
        candidate_rejection_summary = CandidateRejectionSummaryEngine().evaluate(opportunity_queue.get('queue', []))
        readiness_heatmap = ReadinessHeatmapEngine().evaluate(opportunity_queue.get('queue', []))
        opportunity_autopsy = OpportunityAutopsyEngine().evaluate(opportunity_queue.get('queue', []))
        opportunity_outcome_tracker = OpportunityOutcomeTrackerEngine().record(opportunity_queue.get('queue', []))
        forward_outcome_analyzer = ForwardOutcomeAnalyzerEngine().analyze()
        top_candidate = opportunity_queue.get("top_candidate")
        if top_candidate:
            readiness_acceleration = ReadinessAccelerationEngine().evaluate(top_candidate.get("symbol"))
        else:
            readiness_acceleration = {
                "status": "READINESS_ACCELERATION_NO_CANDIDATE",
                "ready": False,
                "reason": "NO_CANDIDATE",
            }
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
            "why_not_ready": why_not_ready,
            "opportunity_funnel": opportunity_funnel,
            "candidate_rejection_summary": candidate_rejection_summary,
            "readiness_heatmap": readiness_heatmap,
            "opportunity_autopsy": opportunity_autopsy,
            "opportunity_outcome_tracker": opportunity_outcome_tracker,
            "forward_outcome_analyzer": forward_outcome_analyzer,
            "readiness_acceleration": readiness_acceleration,
            "forecast": forecast,
            "status": "MARKET_BATTLEFIELD_FORECAST_READY",
        }
    except Exception as e:
        return {
            "system": "GreyLine",
            "engine": "MarketBattlefieldForecastRoute",
            "status": "MARKET_BATTLEFIELD_FORECAST_ERROR",
            "error_type": type(e).__name__,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
