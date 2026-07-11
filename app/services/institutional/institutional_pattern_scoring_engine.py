
from datetime import datetime


class InstitutionalPatternScoringEngine:
    SCHEMA_VERSION = 1

    def score(self, feature_vector, learned_patterns):

        patterns = (
            learned_patterns.get("patterns")
            or {}
        )

        score = 50.0
        contributions = []

        numeric_fields = [
            "connected_provider_count",
            "uw_available_signal_count",
            "tradestation_component_count",
            "requested_provider_count",
            "degraded_provider_count",
        ]

        for field in numeric_fields:

            if field not in patterns:
                continue

            observed = float(
                feature_vector.get(field, 0)
            )

            learned = float(
                patterns[field].get(
                    "return_mean",
                    0,
                )
            )

            delta = observed * learned

            score += delta * 10

            contributions.append({
                "feature": field,
                "observed": observed,
                "pattern_mean_return": learned,
                "contribution": round(
                    delta * 10,
                    6,
                ),
            })

        score = max(
            0,
            min(
                100,
                round(score, 2),
            ),
        )

        return {
            "timestamp":
                datetime.utcnow().isoformat(),
            "schema_version":
                self.SCHEMA_VERSION,
            "institutional_pattern_score":
                score,
            "contributions":
                contributions,
            "execution_impact":
                "OBSERVATION_ONLY",
            "status":
                "INSTITUTIONAL_PATTERN_SCORE_READY",
        }
