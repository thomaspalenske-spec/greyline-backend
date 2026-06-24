from datetime import datetime

from app.services.forecast_weight_advisor_engine import ForecastWeightAdvisorEngine


class ForecastConfidenceCalibrationEngine:
    def calibrate(self, forecast_score):
        advisor = ForecastWeightAdvisorEngine().advise()

        multiplier = float(
            advisor.get("forecast_weight_multiplier") or 1.0
        )

        calibrated_score = round(
            float(forecast_score) * multiplier,
            2
        )

        if calibrated_score >= 90:
            confidence = "VERY_HIGH"
        elif calibrated_score >= 80:
            confidence = "HIGH"
        elif calibrated_score >= 70:
            confidence = "MODERATE"
        else:
            confidence = "LOW"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastConfidenceCalibrationEngine",
            "raw_forecast_score": forecast_score,
            "forecast_weight_multiplier": multiplier,
            "calibrated_score": calibrated_score,
            "confidence": confidence,
            "status": "FORECAST_CONFIDENCE_CALIBRATION_READY",
        }
