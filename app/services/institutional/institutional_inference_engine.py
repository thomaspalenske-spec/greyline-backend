from datetime import datetime

from app.services.institutional.institutional_feature_vector_engine import (
    InstitutionalFeatureVectorEngine,
)
from app.services.institutional.institutional_pattern_scoring_engine import (
    InstitutionalPatternScoringEngine,
)


class InstitutionalInferenceEngine:

    SCHEMA_VERSION = 2
    MINIMUM_LABELED_SAMPLES = 25
    MODERATE_CONFIDENCE_SAMPLES = 50
    HIGH_CONFIDENCE_SAMPLES = 100

    @classmethod
    def _confidence_state(
        cls,
        sample_count,
    ):
        sample_count = max(
            0,
            int(sample_count or 0),
        )

        if sample_count >= (
            cls.HIGH_CONFIDENCE_SAMPLES
        ):
            return "HIGH"

        if sample_count >= (
            cls.MODERATE_CONFIDENCE_SAMPLES
        ):
            return "MODERATE"

        if sample_count >= (
            cls.MINIMUM_LABELED_SAMPLES
        ):
            return "LOW"

        return "INSUFFICIENT_DATA"

    @classmethod
    def _sample_confidence_pct(
        cls,
        sample_count,
    ):
        sample_count = max(
            0,
            int(sample_count or 0),
        )

        return round(
            min(
                100.0,
                sample_count
                / cls.HIGH_CONFIDENCE_SAMPLES
                * 100.0,
            ),
            2,
        )

    def infer(
        self,
        snapshot,
        patterns,
    ):
        snapshot = (
            snapshot
            if isinstance(snapshot, dict)
            else {}
        )

        patterns = (
            patterns
            if isinstance(patterns, dict)
            else {}
        )

        feature_vector = (
            InstitutionalFeatureVectorEngine()
            .build(snapshot)
        )

        pattern_score = (
            InstitutionalPatternScoringEngine()
            .score(
                feature_vector,
                patterns,
            )
        )

        sample_count = max(
            0,
            int(
                patterns.get(
                    "sample_count"
                )
                or 0
            ),
        )

        confidence_state = (
            self._confidence_state(
                sample_count
            )
        )

        sample_confidence_pct = (
            self._sample_confidence_pct(
                sample_count
            )
        )

        actionable = (
            sample_count
            >= self.MINIMUM_LABELED_SAMPLES
        )

        raw_score = pattern_score.get(
            "institutional_pattern_score"
        )

        try:
            raw_score = float(raw_score)
        except (TypeError, ValueError):
            raw_score = 50.0

        calibrated_score = round(
            50.0
            + (
                raw_score
                - 50.0
            )
            * sample_confidence_pct
            / 100.0,
            2,
        )

        return {
            "timestamp": (
                datetime.utcnow().isoformat()
            ),
            "schema_version": (
                self.SCHEMA_VERSION
            ),
            "symbol": feature_vector.get(
                "symbol"
            ),
            "feature_vector": (
                feature_vector
            ),
            "pattern_score": (
                pattern_score
            ),
            "raw_institutional_pattern_score": (
                round(
                    raw_score,
                    2,
                )
            ),
            "institutional_pattern_score": (
                calibrated_score
            ),
            "labeled_sample_count": (
                sample_count
            ),
            "minimum_labeled_samples": (
                self.MINIMUM_LABELED_SAMPLES
            ),
            "sample_confidence_pct": (
                sample_confidence_pct
            ),
            "confidence_state": (
                confidence_state
            ),
            "actionable": actionable,
            "promotion_state": (
                "VALIDATED_FOR_OBSERVATION"
                if actionable
                else "COLLECTING_LABELED_OUTCOMES"
            ),
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_INFERENCE_READY"
                if actionable
                else
                "INSTITUTIONAL_INFERENCE_"
                "COLLECTING_DATA"
            ),
        }
