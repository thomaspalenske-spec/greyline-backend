from statistics import mean
from typing import Any, Dict, List

from app.services.institutional.institutional_memory_engine import (
    InstitutionalMemoryEngine,
)
from app.services.institutional.institutional_forecast_verification_engine import (
    InstitutionalForecastVerificationEngine,
)


class InstitutionalValidationEngine:
    SIGNALS = [
        "institutional_buying_score",
        "institutional_selling_score",
        "dark_pool_score",
        "dealer_gamma_score",
        "open_interest_score",
        "strike_concentration_score",
        "expiry_alignment_score",
        "variance_risk_score",
        "greek_flow_score",
        "spot_gamma_score",
        "lit_flow_score",
        "market_tide_score",
        "sector_tide_score",
        "ownership_score",
        "short_interest_score",
        "insider_score",
        "congress_score",
        "overall_institutional_score",
    ]

    MINIMUM_RECORDS = 20
    MINIMUM_VERIFIED_FORECASTS = 10
    PROMOTION_CONFIDENCE = 65.0
    HIGH_PROMOTION_CONFIDENCE = 80.0
    DEMOTION_CONFIDENCE = 50.0

    def __init__(self):
        self.memory = InstitutionalMemoryEngine()
        self.forecast_verification = (
            InstitutionalForecastVerificationEngine()
        )

    @staticmethod
    def _float(value: Any):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def evaluate(
        self,
        symbol: str,
        limit: int = 500,
    ) -> Dict[str, Any]:
        symbol = (symbol or "").upper().strip()

        if not symbol:
            raise ValueError("symbol is required")

        records = self.memory.history(symbol, limit=limit)
        snapshots: List[Dict[str, Any]] = [
            record.get("snapshot") or {}
            for record in records
            if isinstance(record, dict)
        ]

        signal_statistics = {}

        for signal in self.SIGNALS:
            values = []

            for snapshot in snapshots:
                value = self._float(snapshot.get(signal))

                if value is not None:
                    values.append(value)

            signal_statistics[signal] = {
                "sample_count": len(values),
                "latest": values[-1] if values else None,
                "minimum": round(min(values), 2) if values else None,
                "maximum": round(max(values), 2) if values else None,
                "average": round(mean(values), 2) if values else None,
                "change": (
                    round(values[-1] - values[0], 2)
                    if len(values) >= 2
                    else 0.0 if len(values) == 1
                    else None
                ),
            }

        overall_values = [
            self._float(snapshot.get("overall_institutional_score"))
            for snapshot in snapshots
        ]
        overall_values = [
            value for value in overall_values
            if value is not None
        ]

        if len(overall_values) >= 3:
            recent_window = overall_values[-3:]
            institutional_trend = (
                "IMPROVING"
                if recent_window[-1] > recent_window[0]
                else "DETERIORATING"
                if recent_window[-1] < recent_window[0]
                else "STABLE"
            )
        else:
            institutional_trend = "INSUFFICIENT_HISTORY"

        record_count_validated = (
            len(overall_values)
            >= self.MINIMUM_RECORDS
        )

        try:
            forecast_verification = (
                self.forecast_verification.evaluate(
                    symbol,
                    limit=limit,
                    minimum_verified_forecasts=(
                        self.MINIMUM_VERIFIED_FORECASTS
                    ),
                )
            )
        except Exception as exc:
            forecast_verification = {
                "symbol": symbol,
                "verified_forecast_count": 0,
                "verification_available": False,
                "calibrated_forecast_confidence": 0.0,
                "forecast_trust_state": (
                    "VERIFICATION_DEGRADED"
                ),
                "execution_impact": "OBSERVATION_ONLY",
                "error": repr(exc),
                "status": (
                    "INSTITUTIONAL_FORECAST_"
                    "VERIFICATION_DEGRADED"
                ),
            }

        verified_forecast_count = int(
            forecast_verification.get(
                "verified_forecast_count"
            )
            or 0
        )

        calibrated_confidence = float(
            forecast_verification.get(
                "calibrated_forecast_confidence"
            )
            or 0.0
        )

        verification_available = bool(
            forecast_verification.get(
                "verification_available"
            )
        )

        predictive_validated = bool(
            record_count_validated
            and verification_available
            and verified_forecast_count
            >= self.MINIMUM_VERIFIED_FORECASTS
            and calibrated_confidence
            >= self.PROMOTION_CONFIDENCE
        )

        if not record_count_validated:
            promotion_state = "COLLECTING_RECORDS"
            promotion_reason = (
                "MINIMUM_RECORD_COUNT_NOT_REACHED"
            )
        elif not verification_available:
            promotion_state = (
                "COLLECTING_VERIFICATION"
            )
            promotion_reason = (
                "MINIMUM_VERIFIED_FORECASTS_"
                "NOT_REACHED"
            )
        elif (
            calibrated_confidence
            >= self.HIGH_PROMOTION_CONFIDENCE
        ):
            promotion_state = "HIGHLY_VALIDATED"
            promotion_reason = (
                "HIGH_FORECAST_CONFIDENCE"
            )
        elif (
            calibrated_confidence
            >= self.PROMOTION_CONFIDENCE
        ):
            promotion_state = "VALIDATED"
            promotion_reason = (
                "FORECAST_CONFIDENCE_VALIDATED"
            )
        elif (
            calibrated_confidence
            < self.DEMOTION_CONFIDENCE
        ):
            promotion_state = "DEMOTED"
            promotion_reason = (
                "FORECAST_CONFIDENCE_BELOW_"
                "DEMOTION_THRESHOLD"
            )
        else:
            promotion_state = "OBSERVATION_ONLY"
            promotion_reason = (
                "FORECAST_CONFIDENCE_NOT_YET_"
                "PROMOTABLE"
            )

        execution_impact = (
            "PREDICTIVE_VALIDATION_ELIGIBLE"
            if predictive_validated
            else "OBSERVATION_ONLY"
        )

        return {
            "symbol": symbol,
            "record_count": len(records),
            "scored_record_count": len(
                overall_values
            ),

            # Preserve the existing record-count validation
            # contract until the execution gate is upgraded
            # in a separate, explicitly validated change.
            "validated": record_count_validated,
            "record_count_validated": (
                record_count_validated
            ),
            "predictive_validated": (
                predictive_validated
            ),
            "minimum_validation_records": (
                self.MINIMUM_RECORDS
            ),
            "minimum_verified_forecasts": (
                self.MINIMUM_VERIFIED_FORECASTS
            ),
            "promotion_confidence_threshold": (
                self.PROMOTION_CONFIDENCE
            ),
            "high_promotion_confidence_threshold": (
                self.HIGH_PROMOTION_CONFIDENCE
            ),
            "demotion_confidence_threshold": (
                self.DEMOTION_CONFIDENCE
            ),
            "promotion_state": promotion_state,
            "promotion_reason": promotion_reason,
            "institutional_trend": (
                institutional_trend
            ),
            "signal_statistics": signal_statistics,
            "forecast_verification": (
                forecast_verification
            ),
            "verified_forecast_count": (
                verified_forecast_count
            ),
            "calibrated_forecast_confidence": (
                round(
                    calibrated_confidence,
                    2,
                )
            ),
            "forecast_trust_state": (
                forecast_verification.get(
                    "forecast_trust_state"
                )
            ),
            "execution_impact": execution_impact,
            "status": (
                "INSTITUTIONAL_VALIDATION_READY"
                if record_count_validated
                else
                "INSTITUTIONAL_VALIDATION_"
                "COLLECTING_DATA"
            ),
        }
