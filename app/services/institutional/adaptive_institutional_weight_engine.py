from __future__ import annotations

from typing import Any, Dict

from app.services.institutional.institutional_forecast_verification_engine import (
    InstitutionalForecastVerificationEngine,
)


class AdaptiveInstitutionalWeightEngine:
    """
    Adjusts institutional scoring weight only after forecast performance
    has been sufficiently verified.

    Safety controls:
    - Current GreyLine weights remain the baseline.
    - Insufficient verification produces no scoring change.
    - Institutional influence is bounded.
    - All weights are renormalized to exactly 1.0.
    - Failures return the unchanged baseline profile.
    """

    BULLISH_BASELINE = {
        "market_data": 0.08,
        "liquidity": 0.11,
        "setup": 0.13,
        "regime": 0.11,
        "volatility": 0.07,
        "expected_value": 0.10,
        "trend": 0.09,
        "breadth": 0.08,
        "institutional_flow": 0.06,
        "institutional_conviction": 0.02,
        "asymmetry": 0.08,
        "risk": 0.07,
    }

    BEARISH_BASELINE = {
        "market_data": 0.08,
        "liquidity": 0.11,
        "setup": 0.08,
        "regime": 0.13,
        "volatility": 0.12,
        "expected_value": 0.09,
        "trend": 0.10,
        "breadth": 0.10,
        "institutional_flow": 0.06,
        "institutional_conviction": 0.02,
        "asymmetry": 0.06,
        "risk": 0.05,
    }

    MINIMUM_VERIFIED_FORECASTS = 5

    # Combined institutional baseline is 8%.
    MIN_INSTITUTIONAL_TOTAL_WEIGHT = 0.04
    MAX_INSTITUTIONAL_TOTAL_WEIGHT = 0.12

    def __init__(self):
        self.verification = InstitutionalForecastVerificationEngine()

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize(weights: Dict[str, float]) -> Dict[str, float]:
        total = sum(max(0.0, float(value)) for value in weights.values())

        if total <= 0:
            return dict(weights)

        normalized = {
            key: max(0.0, float(value)) / total
            for key, value in weights.items()
        }

        # Preserve an exact 1.0 total after rounding drift by applying
        # the residual to the largest non-institutional component.
        rounded = {
            key: round(value, 6)
            for key, value in normalized.items()
        }

        residual = round(1.0 - sum(rounded.values()), 6)

        if residual:
            target = max(
                (
                    key
                    for key in rounded
                    if key not in {
                        "institutional_flow",
                        "institutional_conviction",
                    }
                ),
                key=lambda key: rounded[key],
            )
            rounded[target] = round(
                rounded[target] + residual,
                6,
            )

        return rounded

    def _baseline(self, side: str) -> Dict[str, float]:
        if side == "PUT":
            return dict(self.BEARISH_BASELINE)

        return dict(self.BULLISH_BASELINE)

    def evaluate(
        self,
        symbol: str,
        side: str,
    ) -> Dict[str, Any]:
        symbol = (symbol or "").upper().strip()
        side = (side or "CALL").upper().strip()

        baseline = self._baseline(side)

        try:
            verification = self.verification.evaluate(
                symbol,
                minimum_verified_forecasts=(
                    self.MINIMUM_VERIFIED_FORECASTS
                ),
            )
        except Exception as exc:
            return {
                "symbol": symbol,
                "side": side,
                "actionable": False,
                "weights": baseline,
                "baseline_weights": baseline,
                "institutional_total_weight": round(
                    baseline["institutional_flow"]
                    + baseline["institutional_conviction"],
                    6,
                ),
                "weight_multiplier": 1.0,
                "reason": "VERIFICATION_ENGINE_DEGRADED",
                "error": repr(exc),
                "execution_impact": "BASELINE_FALLBACK",
                "status": "ADAPTIVE_INSTITUTIONAL_WEIGHT_DEGRADED",
            }

        verified_count = int(
            verification.get("verified_forecast_count") or 0
        )
        available = (
            verification.get("verification_available") is True
        )
        trust_state = verification.get("forecast_trust_state")
        calibrated_confidence = self._float(
            verification.get(
                "calibrated_forecast_confidence"
            )
        )
        accuracy_score = self._float(
            verification.get("forecast_accuracy_score")
        )
        directional_accuracy = self._float(
            verification.get("directional_accuracy_pct")
        )

        if (
            not available
            or verified_count < self.MINIMUM_VERIFIED_FORECASTS
            or trust_state == "INSUFFICIENT_VERIFICATION"
        ):
            return {
                "symbol": symbol,
                "side": side,
                "actionable": False,
                "weights": baseline,
                "baseline_weights": baseline,
                "verified_forecast_count": verified_count,
                "forecast_trust_state": trust_state,
                "calibrated_forecast_confidence": (
                    calibrated_confidence
                ),
                "institutional_total_weight": round(
                    baseline["institutional_flow"]
                    + baseline["institutional_conviction"],
                    6,
                ),
                "weight_multiplier": 1.0,
                "reason": "INSUFFICIENT_VERIFIED_FORECASTS",
                "execution_impact": "BASELINE_ONLY",
                "status": (
                    "ADAPTIVE_INSTITUTIONAL_WEIGHT_COLLECTING_DATA"
                ),
            }

        quality = (
            accuracy_score * 0.45
            + calibrated_confidence * 0.35
            + directional_accuracy * 0.20
        )

        # Quality 50 maps to baseline.
        # Quality 100 maps to 1.5x.
        # Quality 0 maps to 0.5x.
        multiplier = max(
            0.50,
            min(
                1.50,
                0.50 + quality / 100.0,
            ),
        )

        baseline_institutional_total = (
            baseline["institutional_flow"]
            + baseline["institutional_conviction"]
        )

        institutional_total = max(
            self.MIN_INSTITUTIONAL_TOTAL_WEIGHT,
            min(
                self.MAX_INSTITUTIONAL_TOTAL_WEIGHT,
                baseline_institutional_total * multiplier,
            ),
        )

        flow_share = (
            baseline["institutional_flow"]
            / baseline_institutional_total
        )
        conviction_share = (
            baseline["institutional_conviction"]
            / baseline_institutional_total
        )

        adjusted = dict(baseline)
        adjusted["institutional_flow"] = (
            institutional_total * flow_share
        )
        adjusted["institutional_conviction"] = (
            institutional_total * conviction_share
        )

        non_institutional_keys = [
            key
            for key in adjusted
            if key not in {
                "institutional_flow",
                "institutional_conviction",
            }
        ]

        baseline_non_institutional_total = sum(
            baseline[key]
            for key in non_institutional_keys
        )

        remaining_weight = 1.0 - institutional_total

        for key in non_institutional_keys:
            adjusted[key] = (
                baseline[key]
                / baseline_non_institutional_total
                * remaining_weight
            )

        adjusted = self._normalize(adjusted)

        return {
            "symbol": symbol,
            "side": side,
            "actionable": True,
            "weights": adjusted,
            "baseline_weights": baseline,
            "verified_forecast_count": verified_count,
            "forecast_accuracy_score": round(
                accuracy_score,
                2,
            ),
            "directional_accuracy_pct": round(
                directional_accuracy,
                2,
            ),
            "calibrated_forecast_confidence": round(
                calibrated_confidence,
                2,
            ),
            "forecast_trust_state": trust_state,
            "institutional_total_weight": round(
                adjusted["institutional_flow"]
                + adjusted["institutional_conviction"],
                6,
            ),
            "baseline_institutional_total_weight": round(
                baseline_institutional_total,
                6,
            ),
            "weight_multiplier": round(multiplier, 4),
            "quality_score": round(quality, 2),
            "reason": "VERIFIED_FORECAST_PERFORMANCE_APPLIED",
            "execution_impact": "ADAPTIVE_SCORING_ACTIVE",
            "status": "ADAPTIVE_INSTITUTIONAL_WEIGHT_READY",
        }
