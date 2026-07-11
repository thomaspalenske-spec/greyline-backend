
from datetime import datetime

from app.services.institutional.institutional_feature_vector_engine import (
    InstitutionalFeatureVectorEngine,
)
from app.services.institutional.institutional_pattern_scoring_engine import (
    InstitutionalPatternScoringEngine,
)


class InstitutionalInferenceEngine:

    SCHEMA_VERSION = 1

    def infer(self, snapshot, patterns):

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

        return {
            "timestamp":
                datetime.utcnow().isoformat(),
            "schema_version":
                self.SCHEMA_VERSION,
            "symbol":
                feature_vector.get("symbol"),
            "feature_vector":
                feature_vector,
            "pattern_score":
                pattern_score,
            "institutional_pattern_score":
                pattern_score.get(
                    "institutional_pattern_score"
                ),
            "execution_impact":
                "OBSERVATION_ONLY",
            "status":
                "INSTITUTIONAL_INFERENCE_READY",
        }
