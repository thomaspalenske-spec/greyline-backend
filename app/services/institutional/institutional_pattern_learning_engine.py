
from datetime import datetime
from statistics import mean


class InstitutionalPatternLearningEngine:
    SCHEMA_VERSION = 1

    FEATURE_IGNORE = {
        "timestamp",
        "symbol",
        "status",
        "execution_impact",
        "observation_timestamp",
        "realized_return_pct",
        "realized_direction",
        "label_status",
    }

    def train(self, labeled_dataset):

        rows = (
            labeled_dataset.get("rows")
            or labeled_dataset.get("feature_rows")
            or []
        )

        labeled = [
            r for r in rows
            if r.get("label_status")
            == "INSTITUTIONAL_OUTCOME_LABELED"
        ]

        if not labeled:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "schema_version": self.SCHEMA_VERSION,
                "sample_count": 0,
                "patterns": {},
                "execution_impact": "OBSERVATION_ONLY",
                "status": "INSTITUTIONAL_PATTERN_NO_DATA",
            }

        numeric = {}

        for row in labeled:

            for k, v in row.items():

                if k in self.FEATURE_IGNORE:
                    continue

                if isinstance(v, bool):
                    v = int(v)

                if isinstance(v, (int, float)):
                    numeric.setdefault(k, []).append(
                        (
                            float(v),
                            float(
                                row.get(
                                    "realized_return_pct",
                                    0.0,
                                )
                            ),
                        )
                    )

        patterns = {}

        for feature, values in numeric.items():

            xs = [v[0] for v in values]
            ys = [v[1] for v in values]

            patterns[feature] = {
                "count": len(xs),
                "feature_mean": round(mean(xs), 6),
                "return_mean": round(mean(ys), 6),
                "positive_rate_pct":
                    round(
                        100 *
                        sum(
                            y > 0 for y in ys
                        ) / len(ys),
                        2,
                    ),
            }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "schema_version": self.SCHEMA_VERSION,
            "sample_count": len(labeled),
            "patterns": patterns,
            "execution_impact": "OBSERVATION_ONLY",
            "status": "INSTITUTIONAL_PATTERN_READY",
        }
