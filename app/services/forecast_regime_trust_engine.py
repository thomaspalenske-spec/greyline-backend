import json
from datetime import datetime
from math import sqrt
from pathlib import Path


class ForecastRegimeTrustEngine:
    """
    Bayesian trust score computed independently for
    each market regime.
    """

    PRIOR_ALPHA = 5.0
    PRIOR_BETA = 5.0

    def __init__(self):
        self.path = Path("app/data/forecast_outcome_grades.jsonl")

    def evaluate(self, limit=1000):

        if not self.path.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "engine": "ForecastRegimeTrustEngine",
                "regimes": {},
                "status": "NO_FORECAST_HISTORY",
            }

        buckets = {}

        for line in self.path.read_text().splitlines()[-limit:]:

            if not line.strip():
                continue

            try:
                row = json.loads(line)
            except Exception:
                continue

            if row.get("forecast_correct") is None:
                continue

            regime = row.get("regime") or "UNKNOWN"

            b = buckets.setdefault(
                regime,
                {
                    "correct": 0,
                    "incorrect": 0,
                },
            )

            if row.get("forecast_correct"):
                b["correct"] += 1
            else:
                b["incorrect"] += 1

        regimes = {}

        for regime, stats in buckets.items():

            correct = stats["correct"]
            incorrect = stats["incorrect"]

            alpha = self.PRIOR_ALPHA + correct
            beta = self.PRIOR_BETA + incorrect

            mean = alpha / (alpha + beta)

            variance = (
                alpha * beta
                / (
                    (alpha + beta) ** 2
                    * (alpha + beta + 1)
                )
            )

            std = sqrt(variance)

            regimes[regime] = {
                "sample_size": correct + incorrect,
                "correct": correct,
                "incorrect": incorrect,
                "bayesian_accuracy_pct": round(
                    mean * 100,
                    2,
                ),
                "credible_interval_95": {
                    "lower_pct": round(
                        max(0, mean - 1.96 * std) * 100,
                        2,
                    ),
                    "upper_pct": round(
                        min(1, mean + 1.96 * std) * 100,
                        2,
                    ),
                },
            }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastRegimeTrustEngine",
            "regimes": regimes,
            "status": "FORECAST_REGIME_TRUST_READY",
        }
