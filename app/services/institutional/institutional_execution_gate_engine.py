from typing import Any, Dict

from app.services.institutional.institutional_validation_engine import (
    InstitutionalValidationEngine,
)
from app.services.institutional.institutional_forecast_engine import (
    InstitutionalForecastEngine,
)


class InstitutionalExecutionGateEngine:
    MINIMUM_VALIDATION_RECORDS = 20
    MINIMUM_FORECAST_CONFIDENCE = 50.0

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def evaluate(self, symbol: str) -> Dict[str, Any]:
        symbol = (symbol or "").upper().strip()

        validation = InstitutionalValidationEngine().evaluate(symbol)
        forecast = InstitutionalForecastEngine().evaluate(symbol)

        record_count = int(
            validation.get("scored_record_count") or 0
        )

        record_count_validated = (
            validation.get(
                "record_count_validated"
            ) is True
            and record_count
            >= self.MINIMUM_VALIDATION_RECORDS
        )

        predictive_validated = (
            validation.get(
                "predictive_validated"
            ) is True
        )

        validated = (
            record_count_validated
            and predictive_validated
        )

        forecast_available = (
            forecast.get("forecast_available") is True
        )

        trend = str(
            forecast.get("institutional_trend") or "UNKNOWN"
        ).upper()

        forecast_score = self._float(
            forecast.get("projected_score_next_snapshot"),
            50.0,
        )

        forecast_confidence = self._float(
            forecast.get("forecast_confidence"),
            0.0,
        )

        actionable = (
            validated
            and forecast_available
            and forecast_confidence
            >= self.MINIMUM_FORECAST_CONFIDENCE
        )

        allow_execution = True
        multiplier = 1.0
        confidence_adjustment = 0.0
        if not record_count_validated:
            reason = (
                "ADVISORY_ONLY_INSUFFICIENT_RECORDS"
            )
        elif not predictive_validated:
            reason = (
                "ADVISORY_ONLY_PREDICTIVE_"
                "VALIDATION_INCOMPLETE"
            )
        elif not forecast_available:
            reason = (
                "ADVISORY_ONLY_FORECAST_UNAVAILABLE"
            )
        elif (
            forecast_confidence
            < self.MINIMUM_FORECAST_CONFIDENCE
        ):
            reason = (
                "ADVISORY_ONLY_FORECAST_"
                "CONFIDENCE_INSUFFICIENT"
            )
        else:
            reason = (
                "VALIDATED_INSTITUTIONAL_ADVISORY"
            )

        if actionable:
            if trend in {"ACCELERATING", "IMPROVING"}:
                multiplier = 1.05
                confidence_adjustment = 3.0
                reason = "VALIDATED_INSTITUTIONAL_IMPROVEMENT"

            elif trend == "STABLE":
                reason = "VALIDATED_INSTITUTIONAL_STABLE"

            elif trend in {
                "DETERIORATING",
                "DETERIORATING_FAST",
            }:
                multiplier = 0.95
                confidence_adjustment = -3.0
                allow_execution = False
                reason = "VALIDATED_INSTITUTIONAL_DETERIORATION"

            else:
                reason = "VALIDATED_TREND_UNKNOWN"

        return {
            "symbol": symbol,
            "allow_execution": allow_execution,
            "institutional_multiplier": multiplier,
            "confidence_adjustment": confidence_adjustment,
            "actionable": actionable,
            "validated": validated,
            "record_count_validated": (
                record_count_validated
            ),
            "predictive_validated": (
                predictive_validated
            ),
            "promotion_state": validation.get(
                "promotion_state"
            ),
            "promotion_reason": validation.get(
                "promotion_reason"
            ),
            "calibrated_forecast_confidence": (
                validation.get(
                    "calibrated_forecast_confidence"
                )
            ),
            "forecast_trust_state": validation.get(
                "forecast_trust_state"
            ),
            "validation_record_count": record_count,
            "minimum_validation_records":
                self.MINIMUM_VALIDATION_RECORDS,
            "forecast_available": forecast_available,
            "forecast_score": round(forecast_score, 2),
            "forecast_confidence": round(
                forecast_confidence,
                2,
            ),
            "minimum_forecast_confidence":
                self.MINIMUM_FORECAST_CONFIDENCE,
            "institutional_trend": trend,
            "execution_reason": reason,
            "execution_impact": (
                "ACTIVE"
                if actionable
                else "OBSERVATION_ONLY"
            ),
            "status": "INSTITUTIONAL_EXECUTION_GATE_READY",
        }
