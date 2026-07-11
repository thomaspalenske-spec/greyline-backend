
from __future__ import annotations

from datetime import datetime

from app.services.institutional.institutional_model_status_engine import (
    InstitutionalModelStatusEngine,
)


class InstitutionalModelWeightEngine:
    '''
    Observation-only adaptive weighting.

    Produces a recommended multiplier only.
    It never changes opportunity scores or
    execution permissions.
    '''

    SCHEMA_VERSION = 1

    def evaluate(
        self,
        symbol: str,
    ):
        model = (
            InstitutionalModelStatusEngine()
            .evaluate(symbol)
        )

        confidence = (
            model.get(
                "sample_confidence_pct"
            )
            or 0.0
        )

        actionable = bool(
            model.get("actionable")
        )

        if not actionable:
            multiplier = 1.00
            state = "OBSERVATION_ONLY"
        elif confidence >= 95:
            multiplier = 1.15
            state = "HIGH_CONFIDENCE"
        elif confidence >= 80:
            multiplier = 1.10
            state = "MEDIUM_CONFIDENCE"
        else:
            multiplier = 1.05
            state = "LOW_CONFIDENCE"

        return {
            "timestamp":
                datetime.utcnow().isoformat(),
            "schema_version":
                self.SCHEMA_VERSION,
            "symbol":
                symbol.upper(),
            "model_found":
                model.get("model_found"),
            "confidence_state":
                model.get("confidence_state"),
            "sample_confidence_pct":
                confidence,
            "actionable":
                actionable,
            "recommended_multiplier":
                multiplier,
            "execution_impact":
                "OBSERVATION_ONLY",
            "status":
                "INSTITUTIONAL_MODEL_WEIGHT_READY",
            "weight_state":
                state,
        }
