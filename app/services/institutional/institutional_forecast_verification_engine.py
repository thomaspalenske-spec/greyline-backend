from __future__ import annotations

from math import sqrt
from typing import Any, Dict, List

from app.services.institutional.institutional_memory_engine import (
    InstitutionalMemoryEngine,
)


class InstitutionalForecastVerificationEngine:
    """
    Backtests one-snapshot institutional forecasts against realized
    institutional scores already stored in InstitutionalMemoryEngine.

    Observation only. This engine does not alter execution.
    """

    def __init__(self):
        self.memory = InstitutionalMemoryEngine()

    @staticmethod
    def _float(value: Any):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp_score(value: float) -> float:
        return max(0.0, min(100.0, value))

    @staticmethod
    def _direction(delta: float, tolerance: float = 0.25) -> str:
        if delta > tolerance:
            return "UP"
        if delta < -tolerance:
            return "DOWN"
        return "FLAT"

    def _extract_scores(
        self,
        symbol: str,
        limit: int,
    ) -> List[float]:
        records = self.memory.history(symbol, limit=limit)
        scores: List[float] = []

        for record in records:
            snapshot = record.get("snapshot") or {}
            score = self._float(
                snapshot.get("overall_institutional_score")
            )

            if score is not None:
                scores.append(score)

        return scores

    def evaluate(
        self,
        symbol: str,
        limit: int = 100,
        minimum_verified_forecasts: int = 5,
    ) -> Dict[str, Any]:
        symbol = (symbol or "").upper().strip()

        if not symbol:
            raise ValueError("symbol is required")

        scores = self._extract_scores(symbol, limit)

        if len(scores) < 3:
            return {
                "symbol": symbol,
                "scored_record_count": len(scores),
                "verified_forecast_count": 0,
                "verification_available": False,
                "execution_impact": "OBSERVATION_ONLY",
                "status": (
                    "INSTITUTIONAL_FORECAST_VERIFICATION_COLLECTING_DATA"
                ),
            }

        forecasts = []

        for actual_index in range(2, len(scores)):
            training_scores = scores[:actual_index]
            actual_score = scores[actual_index]
            prior_score = training_scores[-1]

            deltas = [
                training_scores[index]
                - training_scores[index - 1]
                for index in range(1, len(training_scores))
            ]

            average_delta = (
                sum(deltas) / len(deltas)
                if deltas
                else 0.0
            )

            predicted_score = self._clamp_score(
                prior_score + average_delta
            )

            error = predicted_score - actual_score
            absolute_error = abs(error)
            squared_error = error * error

            predicted_delta = predicted_score - prior_score
            actual_delta = actual_score - prior_score

            predicted_direction = self._direction(predicted_delta)
            actual_direction = self._direction(actual_delta)
            direction_correct = (
                predicted_direction == actual_direction
            )

            forecasts.append({
                "forecast_number": len(forecasts) + 1,
                "prior_score": round(prior_score, 2),
                "predicted_score": round(predicted_score, 2),
                "actual_score": round(actual_score, 2),
                "error": round(error, 2),
                "absolute_error": round(absolute_error, 2),
                "predicted_direction": predicted_direction,
                "actual_direction": actual_direction,
                "direction_correct": direction_correct,
                "_squared_error": squared_error,
            })

        verified_count = len(forecasts)

        mae = sum(
            item["absolute_error"]
            for item in forecasts
        ) / verified_count

        rmse = sqrt(
            sum(
                item["_squared_error"]
                for item in forecasts
            ) / verified_count
        )

        bias = sum(
            item["error"]
            for item in forecasts
        ) / verified_count

        directional_accuracy = (
            sum(
                1
                for item in forecasts
                if item["direction_correct"]
            )
            / verified_count
        ) * 100.0

        within_2_count = sum(
            1
            for item in forecasts
            if item["absolute_error"] <= 2.0
        )

        within_5_count = sum(
            1
            for item in forecasts
            if item["absolute_error"] <= 5.0
        )

        within_10_count = sum(
            1
            for item in forecasts
            if item["absolute_error"] <= 10.0
        )

        within_2_pct = within_2_count / verified_count * 100.0
        within_5_pct = within_5_count / verified_count * 100.0
        within_10_pct = within_10_count / verified_count * 100.0

        accuracy_score = max(
            0.0,
            min(
                100.0,
                (
                    directional_accuracy * 0.40
                    + within_5_pct * 0.35
                    + within_10_pct * 0.15
                    + max(0.0, 100.0 - mae * 10.0) * 0.10
                ),
            ),
        )

        sample_confidence = min(
            100.0,
            verified_count
            / max(1, minimum_verified_forecasts)
            * 100.0,
        )

        calibrated_confidence = (
            accuracy_score
            * sample_confidence
            / 100.0
        )

        if verified_count < minimum_verified_forecasts:
            trust_state = "INSUFFICIENT_VERIFICATION"
        elif calibrated_confidence >= 80:
            trust_state = "HIGH"
        elif calibrated_confidence >= 65:
            trust_state = "MODERATE"
        elif calibrated_confidence >= 50:
            trust_state = "LOW"
        else:
            trust_state = "UNTRUSTED"

        public_forecasts = []

        for item in forecasts[-10:]:
            public_item = dict(item)
            public_item.pop("_squared_error", None)
            public_forecasts.append(public_item)

        return {
            "symbol": symbol,
            "scored_record_count": len(scores),
            "verified_forecast_count": verified_count,
            "minimum_verified_forecasts":
                minimum_verified_forecasts,
            "verification_available": (
                verified_count >= minimum_verified_forecasts
            ),
            "mean_absolute_error": round(mae, 2),
            "root_mean_squared_error": round(rmse, 2),
            "forecast_bias": round(bias, 2),
            "directional_accuracy_pct": round(
                directional_accuracy,
                2,
            ),
            "within_2_points_pct": round(within_2_pct, 2),
            "within_5_points_pct": round(within_5_pct, 2),
            "within_10_points_pct": round(within_10_pct, 2),
            "forecast_accuracy_score": round(
                accuracy_score,
                2,
            ),
            "sample_confidence": round(
                sample_confidence,
                2,
            ),
            "calibrated_forecast_confidence": round(
                calibrated_confidence,
                2,
            ),
            "forecast_trust_state": trust_state,
            "recent_verified_forecasts": public_forecasts,
            "execution_impact": "OBSERVATION_ONLY",
            "status": (
                "INSTITUTIONAL_FORECAST_VERIFICATION_READY"
                if verified_count >= minimum_verified_forecasts
                else
                "INSTITUTIONAL_FORECAST_VERIFICATION_COLLECTING_DATA"
            ),
        }
