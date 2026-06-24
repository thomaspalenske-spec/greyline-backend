from datetime import datetime

from app.services.forecast_trust_score_engine import ForecastTrustScoreEngine
from app.services.forecast_adaptive_threshold_engine import ForecastAdaptiveThresholdEngine
from app.services.forecast_quality_gate_engine import ForecastQualityGateEngine
from app.services.forecast_deployment_governance_engine import ForecastDeploymentGovernanceEngine


class ForecastInfluenceEngine:
    def evaluate(self, forecast_score=0, confidence="UNKNOWN"):
        trust = ForecastTrustScoreEngine().evaluate()
        adaptive = ForecastAdaptiveThresholdEngine().evaluate()
        quality = ForecastQualityGateEngine().evaluate(
            forecast_score=forecast_score,
            confidence=confidence,
        )
        governance = ForecastDeploymentGovernanceEngine().evaluate(
            forecast_score=forecast_score,
            confidence=confidence,
        )

        quality_gate = quality.get("quality_gate")
        confidence_level = trust.get("confidence_level")
        sample_size = int(trust.get("sample_size") or 0)

        if quality_gate == "BLOCK":
            influence_multiplier = 0.0
            influence_state = "BLOCK_FORECAST_INFLUENCE"
            reason = "QUALITY_GATE_BLOCKED_FORECAST"
        elif sample_size < 10:
            influence_multiplier = 1.0
            influence_state = "OBSERVE_ONLY"
            reason = "INSUFFICIENT_HISTORY_ALLOW_BASELINE_INFLUENCE"
        elif confidence_level == "HIGHLY_TRUSTED":
            influence_multiplier = 1.20
            influence_state = "INCREASE_FORECAST_INFLUENCE"
            reason = "FORECAST_TRUST_HIGH"
        elif confidence_level == "TRUSTED":
            influence_multiplier = 1.10
            influence_state = "MODESTLY_INCREASE_FORECAST_INFLUENCE"
            reason = "FORECAST_TRUST_ACCEPTABLE"
        elif confidence_level == "NEUTRAL":
            influence_multiplier = 1.0
            influence_state = "HOLD_FORECAST_INFLUENCE"
            reason = "FORECAST_TRUST_NEUTRAL"
        elif confidence_level == "DISTRUSTED":
            influence_multiplier = 0.75
            influence_state = "REDUCE_FORECAST_INFLUENCE"
            reason = "FORECAST_TRUST_WEAK"
        else:
            influence_multiplier = 1.0
            influence_state = "HOLD_FORECAST_INFLUENCE"
            reason = "FORECAST_TRUST_UNKNOWN"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastInfluenceEngine",
            "forecast_score": forecast_score,
            "confidence": confidence,
            "sample_size": sample_size,
            "confidence_level": confidence_level,
            "quality_gate": quality_gate,
            "influence_multiplier": influence_multiplier,
            "influence_state": influence_state,
            "reason": reason,
            "trust_score": trust,
            "adaptive_threshold": adaptive,
            "quality_gate_detail": quality,
            "deployment_governance": governance,
            "status": "FORECAST_INFLUENCE_READY",
        }
