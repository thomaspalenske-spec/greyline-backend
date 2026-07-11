import json
from datetime import datetime
from pathlib import Path


class ForecastComponentAttributionEngine:
    HIGH_SIGNAL_THRESHOLD = 70.0
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

    def evaluate(self, limit=500):
        if not self.path.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "engine": "ForecastComponentAttributionEngine",
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

        baseline_accuracy = self._accuracy(rows)
        components = {}

        for field in self.COMPONENT_FIELDS:
            valid_rows = []
            high_rows = []
            low_rows = []

            for row in rows:
                try:
                    value = float(row.get(field))
                except (TypeError, ValueError):
                    continue

                valid_rows.append(row)

                if value >= self.HIGH_SIGNAL_THRESHOLD:
                    high_rows.append(row)
                else:
                    low_rows.append(row)

            accuracy = self._accuracy(valid_rows)
            high_accuracy = self._accuracy(high_rows)
            low_accuracy = self._accuracy(low_rows)

            component_baseline_accuracy = accuracy

            high_lift = round(
                high_accuracy - component_baseline_accuracy,
                2,
            )

            separation = round(
                high_accuracy - low_accuracy,
                2,
            ) if low_rows else 0.0

            actionable = bool(
                len(high_rows) >= self.MIN_BUCKET_SAMPLE
                and len(low_rows) >= self.MIN_BUCKET_SAMPLE
            )

            predictive_score = (
                separation
                if actionable
                else 0.0
            )

            components[field] = {
                "sample_size": len(valid_rows),
                "accuracy_pct": accuracy,
                "baseline_accuracy_pct": component_baseline_accuracy,
                "high_signal_threshold": (
                    self.HIGH_SIGNAL_THRESHOLD
                ),
                "high_signal_sample_size": len(high_rows),
                "high_signal_accuracy_pct": high_accuracy,
                "low_signal_sample_size": len(low_rows),
                "low_signal_accuracy_pct": low_accuracy,
                "high_signal_lift_pct": high_lift,
                "signal_separation_pct": separation,
                "predictive_score_pct": round(
                    predictive_score,
                    2,
                ),
                "actionable": actionable,
            }

        ranked = [
            (
                name,
                data.get("predictive_score_pct") or 0.0,
                data.get("sample_size") or 0,
            )
            for name, data in components.items()
            if data.get("actionable") is True
        ]

        ranked.sort(
            key=lambda item: (
                item[1],
                item[2],
            ),
            reverse=True,
        )

        best_predictor = (
            ranked[0][0]
            if ranked
            else None
        )

        worst_predictor = (
            ranked[-1][0]
            if len(ranked) > 1
            else None
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastComponentAttributionEngine",
            "graded_sample_size": len(rows),
            "baseline_accuracy_pct": baseline_accuracy,
            "components": components,
            "best_predictor": best_predictor,
            "worst_predictor": worst_predictor,
            "status": "FORECAST_COMPONENT_ATTRIBUTION_READY",
        }
