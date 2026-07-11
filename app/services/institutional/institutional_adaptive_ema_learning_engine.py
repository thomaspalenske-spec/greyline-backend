from __future__ import annotations

from math import sqrt
from statistics import mean
from typing import Any, Dict, List

from app.services.institutional.institutional_adaptive_ema_engine import (
    InstitutionalAdaptiveEmaEngine,
)
from app.services.institutional.institutional_memory_engine import (
    InstitutionalMemoryEngine,
)


class InstitutionalAdaptiveEmaLearningEngine:
    """
    Selects a per-symbol EMA alpha using walk-forward forecasts.

    Safety:
    - No look-ahead.
    - Requires sufficient verified forecasts.
    - Does not change execution permissions.
    - Existing profile is retained when learning is unqualified.
    """

    DIRECTION_TOLERANCE = 0.25

    def __init__(self):
        self.memory = InstitutionalMemoryEngine()
        self.profiles = InstitutionalAdaptiveEmaEngine()

    @staticmethod
    def _float(value: Any):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp(value: float) -> float:
        return max(
            0.0,
            min(
                100.0,
                value,
            ),
        )

    @classmethod
    def _direction(cls, delta: float) -> str:
        if delta > cls.DIRECTION_TOLERANCE:
            return "UP"

        if delta < -cls.DIRECTION_TOLERANCE:
            return "DOWN"

        return "FLAT"

    @staticmethod
    def _ema(
        values: List[float],
        alpha: float,
    ) -> float:
        ema = values[0]

        for value in values[1:]:
            ema = (
                alpha * value
                + (1.0 - alpha) * ema
            )

        return ema

    def _scores(
        self,
        symbol: str,
        limit: int,
    ) -> List[float]:
        rows = self.memory.history(
            symbol,
            limit=limit,
        )

        scores: List[float] = []

        for row in rows:
            snapshot = row.get("snapshot") or {}

            value = self._float(
                snapshot.get(
                    "overall_institutional_score"
                )
            )

            if value is not None:
                scores.append(value)

        return scores

    def _evaluate_alpha(
        self,
        scores: List[float],
        alpha: float,
    ) -> Dict[str, Any]:
        forecasts = []

        for actual_index in range(
            2,
            len(scores),
        ):
            training_scores = scores[
                :actual_index
            ]

            prior_score = training_scores[-1]
            actual_score = scores[actual_index]

            deltas = [
                training_scores[index]
                - training_scores[index - 1]
                for index in range(
                    1,
                    len(training_scores),
                )
            ]

            ema_delta = (
                self._ema(
                    deltas,
                    alpha,
                )
                if deltas
                else 0.0
            )

            predicted_score = self._clamp(
                prior_score + ema_delta
            )

            error = (
                predicted_score
                - actual_score
            )

            forecasts.append({
                "absolute_error": abs(error),
                "squared_error": error * error,
                "direction_correct": (
                    self._direction(
                        predicted_score
                        - prior_score
                    )
                    == self._direction(
                        actual_score
                        - prior_score
                    )
                ),
            })

        forecast_count = len(forecasts)

        if forecast_count == 0:
            return {
                "alpha": alpha,
                "verified_forecast_count": 0,
                "mean_absolute_error": None,
                "root_mean_squared_error": None,
                "directional_accuracy_pct": None,
                "selection_score": 0.0,
            }

        mae = mean(
            row["absolute_error"]
            for row in forecasts
        )

        rmse = sqrt(
            mean(
                row["squared_error"]
                for row in forecasts
            )
        )

        directional_accuracy = (
            sum(
                1
                for row in forecasts
                if row["direction_correct"]
            )
            / forecast_count
            * 100.0
        )

        error_quality = max(
            0.0,
            100.0 - mae * 10.0,
        )

        rmse_quality = max(
            0.0,
            100.0 - rmse * 10.0,
        )

        selection_score = (
            directional_accuracy * 0.50
            + error_quality * 0.35
            + rmse_quality * 0.15
        )

        return {
            "alpha": round(alpha, 3),
            "verified_forecast_count": (
                forecast_count
            ),
            "mean_absolute_error": round(
                mae,
                4,
            ),
            "root_mean_squared_error": round(
                rmse,
                4,
            ),
            "directional_accuracy_pct": round(
                directional_accuracy,
                2,
            ),
            "selection_score": round(
                selection_score,
                4,
            ),
        }

    def evaluate(
        self,
        symbol: str,
        limit: int = 500,
        persist: bool = True,
    ) -> Dict[str, Any]:
        symbol = (
            symbol
            or ""
        ).upper().strip()

        if not symbol:
            raise ValueError(
                "symbol is required"
            )

        scores = self._scores(
            symbol,
            limit,
        )

        verified_forecast_count = max(
            0,
            len(scores) - 2,
        )

        current_alpha = self.profiles.alpha(
            symbol
        )

        if (
            verified_forecast_count
            < self.profiles.MIN_VERIFIED_FORECASTS
        ):
            return {
                "symbol": symbol,
                "scored_record_count": len(scores),
                "verified_forecast_count": (
                    verified_forecast_count
                ),
                "minimum_verified_forecasts": (
                    self.profiles
                    .MIN_VERIFIED_FORECASTS
                ),
                "current_alpha": current_alpha,
                "selected_alpha": None,
                "profile_updated": False,
                "reason": (
                    "INSUFFICIENT_VERIFIED_FORECASTS"
                ),
                "execution_impact": (
                    "OBSERVATION_ONLY"
                ),
                "status": (
                    "INSTITUTIONAL_ADAPTIVE_EMA_"
                    "LEARNING_COLLECTING_DATA"
                ),
            }

        candidates = [
            self._evaluate_alpha(
                scores,
                alpha,
            )
            for alpha in (
                self.profiles
                .candidate_alphas()
            )
        ]

        candidates.sort(
            key=lambda row: (
                row.get(
                    "selection_score"
                )
                or 0.0,
                -(
                    row.get(
                        "mean_absolute_error"
                    )
                    or float("inf")
                ),
                -abs(
                    (
                        row.get("alpha")
                        or self.profiles.DEFAULT_ALPHA
                    )
                    - self.profiles.DEFAULT_ALPHA
                ),
            ),
            reverse=True,
        )

        best = candidates[0]
        selected_alpha = float(
            best["alpha"]
        )

        profile_updated = False

        if persist:
            profile_data = (
                self.profiles._load()
            )

            previous = profile_data.get(
                symbol
            )

            profile = {
                "alpha": selected_alpha,
                "verified_forecast_count": (
                    verified_forecast_count
                ),
                "selection_score": best.get(
                    "selection_score"
                ),
                "mean_absolute_error": best.get(
                    "mean_absolute_error"
                ),
                "root_mean_squared_error": best.get(
                    "root_mean_squared_error"
                ),
                "directional_accuracy_pct": (
                    best.get(
                        "directional_accuracy_pct"
                    )
                ),
            }

            if previous != profile:
                profile_data[symbol] = profile
                self.profiles.save_profiles(
                    profile_data
                )
                profile_updated = True

        return {
            "symbol": symbol,
            "scored_record_count": len(scores),
            "verified_forecast_count": (
                verified_forecast_count
            ),
            "minimum_verified_forecasts": (
                self.profiles.MIN_VERIFIED_FORECASTS
            ),
            "current_alpha": current_alpha,
            "selected_alpha": selected_alpha,
            "profile_updated": profile_updated,
            "selected_metrics": best,
            "candidate_results": candidates,
            "reason": (
                "QUALIFIED_ALPHA_SELECTED"
            ),
            "execution_impact": (
                "FORECAST_MODEL_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_ADAPTIVE_EMA_"
                "LEARNING_READY"
            ),
        }
