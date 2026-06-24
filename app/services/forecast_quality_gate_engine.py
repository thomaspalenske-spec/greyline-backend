from datetime import datetime

from app.services.forecast_adaptive_threshold_engine import ForecastAdaptiveThresholdEngine
from app.services.forecast_trust_score_engine import ForecastTrustScoreEngine
from app.services.forecast_meta_learning_engine import ForecastMetaLearningEngine


class ForecastQualityGateEngine:
    def evaluate(self, forecast_score=0, confidence="UNKNOWN"):
        adaptive = ForecastAdaptiveThresholdEngine().evaluate()
        trust = ForecastTrustScoreEngine().evaluate()
        meta = ForecastMetaLearningEngine().evaluate()

        required_threshold = float(adaptive.get("forecast_threshold") or 80)
        score = float(forecast_score or 0)

        if trust.get("confidence_level") == "INSUFFICIENT_DATA":
            quality_gate = "PASS"
            reason = "INSUFFICIENT_HISTORY_ALLOW_OBSERVATION"
            historical_edge = None
        elif score >= required_threshold:
            quality_gate = "PASS"
            reason = "FORECAST_SCORE_MEETS_ADAPTIVE_THRESHOLD"
            historical_edge = True
        else:
            quality_gate = "BLOCK"
            reason = "FORECAST_SCORE_BELOW_ADAPTIVE_THRESHOLD"
            historical_edge = False

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastQualityGateEngine",
            "forecast_score": score,
            "confidence": confidence,
            "required_threshold": required_threshold,
            "quality_gate": quality_gate,
            "historical_edge": historical_edge,
            "reason": reason,
            "trust_score": trust,
            "adaptive_threshold": adaptive,
            "meta_learning": meta,
            "status": "FORECAST_QUALITY_GATE_READY",
        }
