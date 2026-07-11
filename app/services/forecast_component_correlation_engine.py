import json
import math
from datetime import datetime
from itertools import combinations
from pathlib import Path


class ForecastComponentCorrelationEngine:
    FIELDS = [
        "regime_score",
        "risk_state_score",
        "breadth_score",
        "setup_score",
        "asymmetry_score",
        "volatility_score",
    ]

    MIN_SAMPLE = 20
    REDUNDANCY_THRESHOLD = 0.85

    def __init__(self):
        self.path = Path(
            "app/data/forecast_outcome_grades.jsonl"
        )

    @staticmethod
    def _correlation(xs, ys):
        n = len(xs)

        if n < 2:
            return None

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        covariance = sum(
            (x - mean_x) * (y - mean_y)
            for x, y in zip(xs, ys)
        )

        variance_x = sum(
            (x - mean_x) ** 2
            for x in xs
        )

        variance_y = sum(
            (y - mean_y) ** 2
            for y in ys
        )

        denominator = math.sqrt(
            variance_x * variance_y
        )

        if denominator == 0:
            return None

        return round(
            covariance / denominator,
            4,
        )

    def evaluate(self, limit=500):
        if not self.path.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "engine": (
                    "ForecastComponentCorrelationEngine"
                ),
                "pairs": [],
                "redundant_pairs": [],
                "status": "NO_FORECAST_GRADE_DATA",
            }

        rows = []

        for line in self.path.read_text().splitlines()[-limit:]:
            try:
                row = json.loads(line)
            except Exception:
                continue

            if row.get("forecast_correct") is None:
                continue

            rows.append(row)

        pairs = []

        for left, right in combinations(
            self.FIELDS,
            2,
        ):
            values = []

            for row in rows:
                try:
                    left_value = float(row.get(left))
                    right_value = float(row.get(right))
                except (TypeError, ValueError):
                    continue

                values.append(
                    (left_value, right_value)
                )

            correlation = self._correlation(
                [x for x, _ in values],
                [y for _, y in values],
            )

            absolute_correlation = (
                abs(correlation)
                if correlation is not None
                else None
            )

            redundant = bool(
                len(values) >= self.MIN_SAMPLE
                and absolute_correlation is not None
                and absolute_correlation
                >= self.REDUNDANCY_THRESHOLD
            )

            pairs.append({
                "left": left,
                "right": right,
                "sample_size": len(values),
                "correlation": correlation,
                "absolute_correlation": (
                    absolute_correlation
                ),
                "redundant": redundant,
            })

        pairs.sort(
            key=lambda row: (
                row.get("absolute_correlation")
                if row.get("absolute_correlation")
                is not None
                else -1
            ),
            reverse=True,
        )

        redundant_pairs = [
            row
            for row in pairs
            if row.get("redundant")
        ]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": (
                "ForecastComponentCorrelationEngine"
            ),
            "sample_size": len(rows),
            "redundancy_threshold": (
                self.REDUNDANCY_THRESHOLD
            ),
            "pairs": pairs,
            "redundant_pairs": redundant_pairs,
            "status": (
                "FORECAST_COMPONENT_CORRELATION_READY"
            ),
        }
