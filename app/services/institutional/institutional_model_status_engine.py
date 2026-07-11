from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from app.services.institutional.institutional_model_repository_engine import (
    InstitutionalModelRepositoryEngine,
)


class InstitutionalModelStatusEngine:
    """
    Reads the latest persisted institutional model.

    Observation only:
    - no retraining
    - no scoring changes
    - no execution influence
    """

    def __init__(self):
        self.repository = (
            InstitutionalModelRepositoryEngine()
        )

    @staticmethod
    def _symbol(symbol: str) -> str:
        value = (
            symbol
            or ""
        ).upper().strip()

        if not value:
            raise ValueError(
                "symbol is required"
            )

        return value

    def evaluate(
        self,
        symbol: str,
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)

        loaded = self.repository.load(
            symbol
        )

        model = (
            loaded.get("model")
            or {}
        )

        if loaded.get("model_found") is not True:
            return {
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
                "symbol": symbol,
                "model_found": False,
                "model_timestamp": None,
                "labeled_sample_count": 0,
                "minimum_labeled_samples": 25,
                "sample_confidence_pct": 0.0,
                "confidence_state": (
                    "INSUFFICIENT_DATA"
                ),
                "institutional_pattern_score": 50.0,
                "actionable": False,
                "promotion_state": (
                    "MODEL_NOT_AVAILABLE"
                ),
                "execution_impact": (
                    "OBSERVATION_ONLY"
                ),
                "status": (
                    "INSTITUTIONAL_MODEL_"
                    "STATUS_UNAVAILABLE"
                ),
            }

        labeled_sample_count = int(
            model.get(
                "labeled_sample_count"
            )
            or model.get(
                "labeled_count"
            )
            or 0
        )

        minimum_labeled_samples = int(
            model.get(
                "minimum_labeled_samples"
            )
            or 25
        )

        actionable = (
            model.get("actionable")
            is True
            and labeled_sample_count
            >= minimum_labeled_samples
        )

        try:
            pattern_score = float(
                model.get(
                    "institutional_pattern_score"
                )
            )
        except (TypeError, ValueError):
            pattern_score = 50.0

        try:
            sample_confidence_pct = float(
                model.get(
                    "sample_confidence_pct"
                )
                or 0.0
            )
        except (TypeError, ValueError):
            sample_confidence_pct = 0.0

        return {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "symbol": symbol,
            "model_found": True,
            "model_timestamp": loaded.get(
                "timestamp"
            ),
            "source_snapshot_count": model.get(
                "source_snapshot_count"
            ),
            "labeled_sample_count": (
                labeled_sample_count
            ),
            "minimum_labeled_samples": (
                minimum_labeled_samples
            ),
            "sample_confidence_pct": round(
                sample_confidence_pct,
                2,
            ),
            "confidence_state": model.get(
                "confidence_state"
            )
            or "INSUFFICIENT_DATA",
            "institutional_pattern_score": round(
                pattern_score,
                2,
            ),
            "raw_institutional_pattern_score": (
                model.get(
                    "raw_institutional_pattern_score"
                )
            ),
            "pattern_count": model.get(
                "pattern_count"
            ),
            "actionable": actionable,
            "promotion_state": model.get(
                "promotion_state"
            )
            or (
                "VALIDATED_FOR_OBSERVATION"
                if actionable
                else "COLLECTING_LABELED_OUTCOMES"
            ),
            "model_repository_status": (
                loaded.get("status")
            ),
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_MODEL_STATUS_READY"
            ),
        }
