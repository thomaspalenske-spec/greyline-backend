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
from app.services.forward_outcome_capture_engine import ForwardOutcomeCaptureEngine
from app.services.battlefield_prediction_accuracy_engine import BattlefieldPredictionAccuracyEngine
from app.services.forward_outcome_grading_engine import ForwardOutcomeGradingEngine
from app.services.battlefield_learning_engine import BattlefieldLearningEngine
from app.services.battlefield_adaptive_weight_advisor_engine import BattlefieldAdaptiveWeightAdvisorEngine
from app.services.learning_sample_quality_gate_engine import LearningSampleQualityGateEngine
from app.services.battlefield_learning_ledger_engine import BattlefieldLearningLedgerEngine
from app.services.learning_horizon_analysis_engine import LearningHorizonAnalysisEngine
from app.services.signal_maturity_engine import SignalMaturityEngine
from app.services.forward_outcome_horizon_tracker_engine import ForwardOutcomeHorizonTrackerEngine
from app.services.horizon_readiness_gate_engine import HorizonReadinessGateEngine
from app.services.horizon_one_hour_performance_engine import HorizonOneHourPerformanceEngine

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
        forward_outcome_capture = ForwardOutcomeCaptureEngine().capture()
        battlefield_prediction_accuracy = BattlefieldPredictionAccuracyEngine().evaluate(forward_outcome_capture.get('outcomes', []))
        forward_outcome_grading = ForwardOutcomeGradingEngine().grade(forward_outcome_capture.get('outcomes', []))
        battlefield_learning = BattlefieldLearningEngine().evaluate(forward_outcome_grading.get('grades', []))
        learning_sample_quality_gate = LearningSampleQualityGateEngine().evaluate(battlefield_learning, forward_outcome_grading)
        battlefield_adaptive_weight_advisor = BattlefieldAdaptiveWeightAdvisorEngine().evaluate(battlefield_learning)
        battlefield_learning_ledger = BattlefieldLearningLedgerEngine().record(battlefield_learning, learning_sample_quality_gate, battlefield_adaptive_weight_advisor)
        learning_horizon_analysis = LearningHorizonAnalysisEngine().analyze()
        signal_maturity = SignalMaturityEngine().evaluate()
        forward_outcome_horizon_tracker = ForwardOutcomeHorizonTrackerEngine().evaluate()
        horizon_readiness_gate = HorizonReadinessGateEngine().evaluate(forward_outcome_horizon_tracker)
        horizon_one_hour_performance = HorizonOneHourPerformanceEngine().evaluate()
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
            "forward_outcome_capture": forward_outcome_capture,
            "battlefield_prediction_accuracy": battlefield_prediction_accuracy,
            "forward_outcome_grading": forward_outcome_grading,
            "battlefield_learning": battlefield_learning,
            "learning_sample_quality_gate": learning_sample_quality_gate,
            "battlefield_adaptive_weight_advisor": battlefield_adaptive_weight_advisor,
            "battlefield_learning_ledger": battlefield_learning_ledger,
            "learning_horizon_analysis": learning_horizon_analysis,
            "signal_maturity": signal_maturity,
            "forward_outcome_horizon_tracker": forward_outcome_horizon_tracker,
            "horizon_readiness_gate": horizon_readiness_gate,
            "horizon_one_hour_performance": horizon_one_hour_performance,
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
