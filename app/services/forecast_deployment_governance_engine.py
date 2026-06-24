from datetime import datetime

from app.services.forecast_feedback_engine import ForecastFeedbackEngine
from app.services.forecast_weight_advisor_engine import ForecastWeightAdvisorEngine
from app.services.forecast_horizon_attribution_engine import ForecastHorizonAttributionEngine
from app.services.forecast_regime_attribution_engine import ForecastRegimeAttributionEngine


class ForecastDeploymentGovernanceEngine:
    def evaluate(self, forecast_score=0, confidence="UNKNOWN"):
        feedback = ForecastFeedbackEngine().evaluate()
        weight_advisor = ForecastWeightAdvisorEngine().advise()
        horizon = ForecastHorizonAttributionEngine().evaluate()
        regime = ForecastRegimeAttributionEngine().evaluate()

        historical_accuracy = float(feedback.get("accuracy_pct") or 0)
        sample_size = int(feedback.get("graded_count") or 0)

        weight_multiplier = float(
            weight_advisor.get("forecast_weight_multiplier") or 1.0
        )

        if sample_size < 10:
            trust_score = 50.0
            deployment_modifier = 1.0
            recommendation = "HOLD_DEPLOYMENT_WEIGHT"
            reason = "INSUFFICIENT_MATURE_FORECAST_SAMPLE"
        else:
            trust_score = round(
                (
                    historical_accuracy * 0.60
                    + float(forecast_score or 0) * 0.30
                    + (weight_multiplier * 100) * 0.10
                ),
                2,
            )

            if trust_score >= 75:
                deployment_modifier = 1.15
                recommendation = "INCREASE_POSITION_SIZE"
                reason = "FORECAST_TRUST_STRONG"
            elif trust_score >= 55:
                deployment_modifier = 1.0
                recommendation = "HOLD_POSITION_SIZE"
                reason = "FORECAST_TRUST_ACCEPTABLE"
            else:
                deployment_modifier = 0.5
                recommendation = "REDUCE_POSITION_SIZE"
                reason = "FORECAST_TRUST_WEAK"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastDeploymentGovernanceEngine",
            "forecast_score": forecast_score,
            "confidence": confidence,
            "historical_accuracy_pct": historical_accuracy,
            "sample_size": sample_size,
            "forecast_weight_multiplier": weight_multiplier,
            "trust_score": trust_score,
            "deployment_modifier": deployment_modifier,
            "recommendation": recommendation,
            "reason": reason,
            "horizon_attribution": horizon,
            "regime_attribution": regime,
            "status": "FORECAST_DEPLOYMENT_GOVERNANCE_READY",
        }
