import json
from datetime import datetime
from pathlib import Path


class ForecastComponentAttributionEngine:
    CANDIDATE_THRESHOLDS = [
        40.0,
        50.0,
        60.0,
        70.0,
        80.0,
        90.0,
    ]

    MIN_BUCKET_SAMPLE = 10

    COMPONENT_FIELDS = [
        "regime_score",
        "risk_state_score",
        "breadth_score",
        "setup_score",
        "asymmetry_score",
        "volatility_score",
    ]

    def __init__(self):
        self.path = Path(
            "app/data/forecast_outcome_grades.jsonl"
        )

    @staticmethod
    def _accuracy(rows):
        if not rows:
            return 0.0

        wins = sum(
            1
            for row in rows
            if row.get("forecast_correct") is True
        )

        return round(
            (wins / len(rows)) * 100,
            2,
        )

    def _best_threshold(self, value_rows):
        candidates = []

        for threshold in self.CANDIDATE_THRESHOLDS:
            high_rows = [
                row
                for value, row in value_rows
                if value >= threshold
            ]

            low_rows = [
                row
                for value, row in value_rows
                if value < threshold
            ]

            if (
                len(high_rows) < self.MIN_BUCKET_SAMPLE
                or len(low_rows) < self.MIN_BUCKET_SAMPLE
            ):
                continue

            high_accuracy = self._accuracy(high_rows)
            low_accuracy = self._accuracy(low_rows)

            separation = round(
                high_accuracy - low_accuracy,
                2,
            )

            bucket_balance = min(
                len(high_rows),
                len(low_rows),
            )

            candidates.append({
                "threshold": threshold,
                "high_rows": high_rows,
                "low_rows": low_rows,
                "high_accuracy": high_accuracy,
                "low_accuracy": low_accuracy,
                "separation": separation,
                "absolute_separation": abs(separation),
                "bucket_balance": bucket_balance,
            })

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: (
                item["absolute_separation"],
                item["bucket_balance"],
            ),
            reverse=True,
        )

        return candidates[0]

    def evaluate(self, limit=500):
        if not self.path.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "engine": (
                    "ForecastComponentAttributionEngine"
                ),
                "components": {},
                "best_predictor": None,
                "worst_predictor": None,
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

        components = {}

        for field in self.COMPONENT_FIELDS:
            value_rows = []

            for row in rows:
                try:
                    value = float(row.get(field))
                except (TypeError, ValueError):
                    continue

                value_rows.append((value, row))

            valid_rows = [
                row
                for _, row in value_rows
            ]

            baseline_accuracy = self._accuracy(
                valid_rows
            )

            best = self._best_threshold(value_rows)

            if best is None:
                components[field] = {
                    "sample_size": len(valid_rows),
                    "accuracy_pct": baseline_accuracy,
                    "baseline_accuracy_pct": (
                        baseline_accuracy
                    ),
                    "selected_threshold": None,
                    "high_signal_sample_size": 0,
                    "high_signal_accuracy_pct": 0.0,
                    "low_signal_sample_size": 0,
                    "low_signal_accuracy_pct": 0.0,
                    "high_signal_lift_pct": 0.0,
                    "signal_separation_pct": 0.0,
                    "predictive_score_pct": 0.0,
                    "actionable": False,
                }
                continue

            high_lift = round(
                best["high_accuracy"]
                - baseline_accuracy,
                2,
            )

            components[field] = {
                "sample_size": len(valid_rows),
                "accuracy_pct": baseline_accuracy,
                "baseline_accuracy_pct": (
                    baseline_accuracy
                ),
                "selected_threshold": best[
                    "threshold"
                ],
                "high_signal_sample_size": len(
                    best["high_rows"]
                ),
                "high_signal_accuracy_pct": best[
                    "high_accuracy"
                ],
                "low_signal_sample_size": len(
                    best["low_rows"]
                ),
                "low_signal_accuracy_pct": best[
                    "low_accuracy"
                ],
                "high_signal_lift_pct": high_lift,
                "signal_separation_pct": best[
                    "separation"
                ],
                "predictive_score_pct": best[
                    "separation"
                ],
                "absolute_predictive_score_pct": (
                    best["absolute_separation"]
                ),
                "actionable": True,
            }

        ranked = [
            (
                name,
                float(
                    data.get(
                        "predictive_score_pct"
                    )
                    or 0.0
                ),
                float(
                    data.get(
                        "absolute_predictive_score_pct"
                    )
                    or 0.0
                ),
                int(data.get("sample_size") or 0),
            )
            for name, data in components.items()
            if data.get("actionable") is True
        ]

        positive_ranked = sorted(
            ranked,
            key=lambda item: (
                item[1],
                item[2],
                item[3],
            ),
            reverse=True,
        )

        negative_ranked = sorted(
            ranked,
            key=lambda item: (
                item[1],
                -item[2],
                -item[3],
            ),
        )

        best_predictor = (
            positive_ranked[0][0]
            if positive_ranked
            and positive_ranked[0][1] > 0
            else None
        )

        worst_predictor = (
            negative_ranked[0][0]
            if negative_ranked
            and negative_ranked[0][1] < 0
            else None
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": (
                "ForecastComponentAttributionEngine"
            ),
            "graded_sample_size": len(rows),
            "components": components,
            "best_predictor": best_predictor,
            "worst_predictor": worst_predictor,
            "status": (
                "FORECAST_COMPONENT_ATTRIBUTION_READY"
            ),
        }
