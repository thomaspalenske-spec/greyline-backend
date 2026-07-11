
from datetime import datetime
from statistics import mean


class InstitutionalLearningEngine:
    """
    Observation-only learning engine.

    Consumes institutional feature vectors and produces
    learned feature statistics only.

    NO trading decisions.
    NO score modification.
    NO execution authority.
    """

    SCHEMA_VERSION = 1

    def train(self, dataset):

        rows = (
            dataset.get("rows")
            or dataset.get("feature_rows")
            or []
        )

        if not rows:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "schema_version": self.SCHEMA_VERSION,
                "sample_count": 0,
                "feature_statistics": {},
                "execution_impact": "OBSERVATION_ONLY",
                "status": "INSTITUTIONAL_LEARNING_NO_DATA",
            }

        numeric = {}

        for row in rows:
            for k, v in row.items():

                if isinstance(v, bool):
                    v = int(v)

                if isinstance(v, (int, float)):
                    numeric.setdefault(k, []).append(v)

        stats = {}

        for feature, values in numeric.items():

            stats[feature] = {
                "count": len(values),
                "mean": round(mean(values), 6),
                "minimum": min(values),
                "maximum": max(values),
            }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "schema_version": self.SCHEMA_VERSION,
            "sample_count": len(rows),
            "feature_statistics": stats,
            "execution_impact": "OBSERVATION_ONLY",
            "status": "INSTITUTIONAL_LEARNING_READY",
        }
