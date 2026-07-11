from typing import Any, Dict, List

from app.services.institutional.institutional_memory_engine import (
    InstitutionalMemoryEngine,
)
from app.services.institutional.institutional_adaptive_ema_engine import (
    InstitutionalAdaptiveEmaEngine,
)


class InstitutionalForecastEngine:

    EMA_ALPHA = 0.35

    def __init__(self):
        self.memory = InstitutionalMemoryEngine()
        self.ema_learning = (
            InstitutionalAdaptiveEmaEngine()
        )

    @staticmethod
    def _float(value: Any):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _ema(
        self,
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

    def evaluate(
        self,
        symbol: str,
        limit: int = 20,
    ) -> Dict[str, Any]:
        symbol = (symbol or "").upper().strip()

        if not symbol:
            raise ValueError("symbol is required")

        records = self.memory.history(symbol, limit=limit)

        scores: List[float] = []

        for record in records:
            snapshot = record.get("snapshot") or {}
            score = self._float(
                snapshot.get("overall_institutional_score")
            )

            if score is not None:
                scores.append(score)

        if not scores:
            return {
                "symbol": symbol,
                "record_count": len(records),
                "forecast_available": False,
                "status": "INSTITUTIONAL_FORECAST_NO_DATA",
            }

        current_score = scores[-1]
        ema_alpha = self.ema_learning.alpha(
            symbol
        )

        if len(scores) >= 2:
            deltas = [
                scores[index]
                - scores[index - 1]
                for index in range(
                    1,
                    len(scores),
                )
            ]

            average_delta = self._ema(
                deltas,
                ema_alpha,
            )
        else:
            average_delta = 0.0

        projected_score_1 = max(
            0.0,
            min(
                100.0,
                current_score
                + average_delta,
            ),
        )
        projected_score_3 = max(
            0.0,
            min(100.0, current_score + average_delta * 3),
        )

        if average_delta > 1:
            trend = "ACCELERATING"
        elif average_delta > 0:
            trend = "IMPROVING"
        elif average_delta < -1:
            trend = "DETERIORATING_FAST"
        elif average_delta < 0:
            trend = "DETERIORATING"
        else:
            trend = "STABLE"

        confidence = min(
            100.0,
            round((len(scores) / max(1, limit)) * 100, 2),
        )

        return {
            "symbol": symbol,
            "record_count": len(records),
            "scored_record_count": len(scores),
            "forecast_available": len(scores) >= 2,
            "current_score": round(current_score, 2),
            "average_score_change_per_snapshot": round(
                average_delta,
                2,
            ),
            "projected_score_next_snapshot": round(
                projected_score_1,
                2,
            ),
            "projected_score_three_snapshots": round(
                projected_score_3,
                2,
            ),
            "institutional_trend": trend,
            "forecast_confidence": confidence,
            "ema_alpha": round(
                ema_alpha,
                3,
            ),
            "ema_alpha_source": (
                "ADAPTIVE_EMA_PROFILE"
                if ema_alpha
                != self.EMA_ALPHA
                else "DEFAULT_EMA_ALPHA"
            ),
            "status": (
                "INSTITUTIONAL_FORECAST_READY"
                if len(scores) >= 2
                else "INSTITUTIONAL_FORECAST_COLLECTING_DATA"
            ),
        }
