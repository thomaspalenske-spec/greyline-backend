from datetime import datetime

from app.services.forecast_feedback_engine import ForecastFeedbackEngine


class ForecastWeightAdvisorEngine:
    def advise(self):
        feedback = ForecastFeedbackEngine().evaluate()

        accuracy = float(feedback.get("accuracy_pct") or 0)
        sample_size = int(feedback.get("graded_count") or 0)

        if sample_size < 10:
            recommendation = "HOLD_FORECAST_WEIGHT"
            forecast_weight_multiplier = 1.00
            reason = "INSUFFICIENT_MATURE_FORECAST_SAMPLE"
        elif accuracy >= 65:
            recommendation = "INCREASE_FORECAST_INFLUENCE"
            forecast_weight_multiplier = 1.10
            reason = "FORECAST_ACCURACY_ABOVE_TARGET"
        elif accuracy <= 45:
            recommendation = "REDUCE_FORECAST_INFLUENCE"
            forecast_weight_multiplier = 0.90
            reason = "FORECAST_ACCURACY_BELOW_ACCEPTABLE_THRESHOLD"
        else:
            recommendation = "HOLD_FORECAST_WEIGHT"
            forecast_weight_multiplier = 1.00
            reason = "FORECAST_ACCURACY_WITHIN_NEUTRAL_BAND"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastWeightAdvisorEngine",
            "forecast_accuracy_pct": accuracy,
            "sample_size": sample_size,
            "forecast_weight_multiplier": forecast_weight_multiplier,
            "recommendation": recommendation,
            "reason": reason,
            "feedback": feedback,
            "status": "FORECAST_WEIGHT_ADVISOR_READY",
        }
