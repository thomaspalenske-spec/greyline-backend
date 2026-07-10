import json
from datetime import datetime
from math import sqrt
from pathlib import Path


class ForecastTrustScoreEngine:
    """
    Bayesian-calibrated trust engine for completed forecast grades.

    Uses a Beta prior so small samples cannot produce extreme confidence.
    Existing output fields are preserved for compatibility.
    """

    def __init__(self):
        self.file = Path("app/data/forecast_outcome_grades.jsonl")

        # Conservative neutral prior:
        # 5 prior successes and 5 prior failures.
        self.prior_alpha = 5.0
        self.prior_beta = 5.0

    def _load_grades(self, limit=1000):
        grades = []

        if not self.file.exists():
            return grades

        for line in self.file.read_text().splitlines()[-limit:]:
            if not line.strip():
                continue

            try:
                row = json.loads(line)
            except Exception:
                continue

            if row.get("forecast_correct") is not None:
                grades.append(row)

        return grades

    @staticmethod
    def _confidence_level(
        sample_size,
        posterior_mean_pct,
        lower_bound_pct,
    ):
        if sample_size < 10:
            return "INSUFFICIENT_DATA", 1.0

        if (
            posterior_mean_pct >= 65
            and lower_bound_pct >= 55
        ):
            return "HIGHLY_TRUSTED", 1.2

        if (
            posterior_mean_pct >= 55
            and lower_bound_pct >= 48
        ):
            return "TRUSTED", 1.1

        if posterior_mean_pct >= 45:
            return "NEUTRAL", 1.0

        return "DISTRUSTED", 0.8

    def evaluate(self, limit=1000):
        grades = self._load_grades(limit=limit)

        sample_size = len(grades)
        correct_count = sum(
            1
            for grade in grades
            if grade.get("forecast_correct") is True
        )
        incorrect_count = sample_size - correct_count

        raw_accuracy = (
            correct_count / sample_size * 100.0
            if sample_size
            else 0.0
        )

        posterior_alpha = (
            self.prior_alpha + correct_count
        )
        posterior_beta = (
            self.prior_beta + incorrect_count
        )
        posterior_total = (
            posterior_alpha + posterior_beta
        )

        posterior_mean = (
            posterior_alpha / posterior_total
        )

        posterior_variance = (
            posterior_alpha
            * posterior_beta
            / (
                posterior_total ** 2
                * (posterior_total + 1)
            )
        )
        posterior_std = sqrt(posterior_variance)

        # Normal approximation to the 95% credible interval.
        lower_bound = max(
            0.0,
            posterior_mean - 1.96 * posterior_std,
        )
        upper_bound = min(
            1.0,
            posterior_mean + 1.96 * posterior_std,
        )

        posterior_mean_pct = posterior_mean * 100.0
        lower_bound_pct = lower_bound * 100.0
        upper_bound_pct = upper_bound * 100.0

        confidence, multiplier = self._confidence_level(
            sample_size,
            posterior_mean_pct,
            lower_bound_pct,
        )

        evidence_strength = min(
            100.0,
            sample_size / 50.0 * 100.0,
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastTrustScoreEngine",
            "trust_score": round(
                posterior_mean_pct,
                2,
            ),
            "sample_size": sample_size,
            "correct_count": correct_count,
            "incorrect_count": incorrect_count,
            "accuracy_pct": round(raw_accuracy, 2),
            "bayesian_accuracy_pct": round(
                posterior_mean_pct,
                2,
            ),
            "credible_interval_95": {
                "lower_pct": round(lower_bound_pct, 2),
                "upper_pct": round(upper_bound_pct, 2),
            },
            "prior": {
                "alpha": self.prior_alpha,
                "beta": self.prior_beta,
                "prior_mean_pct": round(
                    self.prior_alpha
                    / (
                        self.prior_alpha
                        + self.prior_beta
                    )
                    * 100.0,
                    2,
                ),
            },
            "posterior": {
                "alpha": round(posterior_alpha, 2),
                "beta": round(posterior_beta, 2),
            },
            "evidence_strength_pct": round(
                evidence_strength,
                2,
            ),
            "confidence_level": confidence,
            "deployment_multiplier": multiplier,
            "execution_impact": (
                "OBSERVATION_ONLY"
                if sample_size < 10
                else "TRUST_GOVERNANCE_ACTIVE"
            ),
            "status": "FORECAST_TRUST_SCORE_READY",
        }
