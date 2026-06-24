from datetime import datetime

from app.services.forecast_trust_score_engine import ForecastTrustScoreEngine


class ForecastAdaptiveThresholdEngine:
    def evaluate(self):
        trust = ForecastTrustScoreEngine().evaluate()
        confidence_level = trust.get("confidence_level")

        if confidence_level == "HIGHLY_TRUSTED":
            forecast_threshold = 70
            deployment_threshold = 65
            forecast_state = "ACCELERATE"
        elif confidence_level == "TRUSTED":
            forecast_threshold = 75
            deployment_threshold = 70
            forecast_state = "NORMAL"
        elif confidence_level == "NEUTRAL":
            forecast_threshold = 80
            deployment_threshold = 75
            forecast_state = "CAUTIOUS"
        elif confidence_level == "DISTRUSTED":
            forecast_threshold = 85
            deployment_threshold = 80
            forecast_state = "RESTRICTED"
        else:
            forecast_threshold = 80
            deployment_threshold = 75
            forecast_state = "INSUFFICIENT_DATA"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastAdaptiveThresholdEngine",
            "trust_score": trust.get("trust_score"),
            "sample_size": trust.get("sample_size"),
            "confidence_level": confidence_level,
            "forecast_threshold": forecast_threshold,
            "deployment_threshold": deployment_threshold,
            "forecast_state": forecast_state,
            "trust": trust,
            "status": "FORECAST_ADAPTIVE_THRESHOLD_READY",
        }
