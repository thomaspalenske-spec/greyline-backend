import json
from datetime import datetime
from pathlib import Path


class ForecastComponentAttributionEngine:
    HOLDOUT_RATIO = 0.20
    MIN_BUCKET_SAMPLE = 10
    MIN_VALIDATION_BUCKET_SAMPLE = 5

    CANDIDATE_THRESHOLDS = [
        40.0,
        50.0,
        60.0,
        70.0,
        80.0,
        90.0,
    ]

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
            wins / len(rows) * 100,
            2,
        )

    @staticmethod
    def _forecast_time(row):
        value = (
            row.get("forecast_timestamp")
            or row.get("forecast_id")
            or ""
        )

        value = str(value)

        if "-20" in value:
            parts = value.split("-")

            for index in range(len(parts)):
                candidate = "-".join(
                    parts[index:index + 3]
                )

                if (
                    len(candidate) >= 10
                    and candidate[:4].isdigit()
                    and candidate[4] == "-"
                    and candidate[7] == "-"
                ):
                    remainder = "-".join(
                        parts[index:index + 4]
                    )

                    return remainder[:19]

        if (
            len(value) >= 19
            and value[:4].isdigit()
            and value[4] == "-"
            and value[7] == "-"
        ):
            return value[:19]

        return str(row.get("timestamp") or "")

    def _load_rows(self, limit):
        raw_rows = []

        if not self.path.exists():
            return raw_rows

        for line in self.path.read_text().splitlines()[-limit:]:
            try:
                row = json.loads(line)
            except Exception:
                continue

            if row.get("forecast_correct") is None:
                continue

            raw_rows.append(row)

        grouped = {}

        for row in raw_rows:
            forecast_time = self._forecast_time(row)

            bucket = forecast_time[:16]

            key = (
                str(row.get("symbol") or "UNKNOWN"),
                str(
                    row.get("predicted_direction")
                    or row.get("directional_bias")
                    or "UNKNOWN"
                ),
                bucket,
            )

            grouped.setdefault(key, []).append(row)

        rows = []
        conflicted_bucket_count = 0

        for grouped_rows in grouped.values():
            outcomes = {
                row.get("forecast_correct")
                for row in grouped_rows
                if row.get("forecast_correct") is not None
            }

            if len(outcomes) != 1:
                conflicted_bucket_count += 1
                continue

            grouped_rows.sort(
                key=lambda row: (
                    self._forecast_time(row),
                    row.get("forecast_id") or "",
                )
            )

            rows.append(grouped_rows[-1])

        rows.sort(
            key=lambda row: (
                self._forecast_time(row),
                row.get("forecast_id") or "",
            )
        )

        self.last_raw_completed_count = len(raw_rows)
        self.last_deduped_count = len(rows)
        self.last_conflicted_bucket_count = (
            conflicted_bucket_count
        )

        return rows

    def _split_rows(self, rows):
        if len(rows) < 25:
            return rows, []

        validation_size = max(
            5,
            int(round(len(rows) * self.HOLDOUT_RATIO)),
        )

        validation_size = min(
            validation_size,
            len(rows) - self.MIN_BUCKET_SAMPLE,
        )

        split_index = len(rows) - validation_size

        return (
            rows[:split_index],
            rows[split_index:],
        )

    def _value_rows(self, rows, field):
        values = []

        for row in rows:
            try:
                value = float(row.get(field))
            except (TypeError, ValueError):
                continue

            values.append((value, row))

        return values

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

            candidates.append({
                "threshold": threshold,
                "high_rows": high_rows,
                "low_rows": low_rows,
                "high_accuracy": high_accuracy,
                "low_accuracy": low_accuracy,
                "separation": separation,
                "absolute_separation": abs(separation),
                "bucket_balance": min(
                    len(high_rows),
                    len(low_rows),
                ),
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

    def _validate_threshold(
        self,
        validation_value_rows,
        threshold,
        training_separation,
    ):
        high_rows = [
            row
            for value, row in validation_value_rows
            if value >= threshold
        ]

        low_rows = [
            row
            for value, row in validation_value_rows
            if value < threshold
        ]

        if (
            len(high_rows)
            < self.MIN_VALIDATION_BUCKET_SAMPLE
            or len(low_rows)
            < self.MIN_VALIDATION_BUCKET_SAMPLE
        ):
            return {
                "validation_high_sample_size": len(high_rows),
                "validation_low_sample_size": len(low_rows),
                "validation_high_accuracy_pct": (
                    self._accuracy(high_rows)
                ),
                "validation_low_accuracy_pct": (
                    self._accuracy(low_rows)
                ),
                "validation_separation_pct": 0.0,
                "validation_passed": False,
                "validation_reason": (
                    "INSUFFICIENT_HOLDOUT_BUCKET_SAMPLE"
                ),
            }

        high_accuracy = self._accuracy(high_rows)
        low_accuracy = self._accuracy(low_rows)

        validation_separation = round(
            high_accuracy - low_accuracy,
            2,
        )

        same_direction = bool(
            training_separation != 0
            and validation_separation != 0
            and (
                training_separation > 0
            ) == (
                validation_separation > 0
            )
        )

        return {
            "validation_high_sample_size": len(high_rows),
            "validation_low_sample_size": len(low_rows),
            "validation_high_accuracy_pct": high_accuracy,
            "validation_low_accuracy_pct": low_accuracy,
            "validation_separation_pct": (
                validation_separation
            ),
            "validation_passed": same_direction,
            "validation_reason": (
                "HOLDOUT_DIRECTION_CONFIRMED"
                if same_direction
                else "HOLDOUT_DIRECTION_FAILED"
            ),
        }

    def evaluate(self, limit=500):
        rows = self._load_rows(limit)

        if not rows:
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

        training_rows, validation_rows = (
            self._split_rows(rows)
        )

        components = {}

        for field in self.COMPONENT_FIELDS:
            training_value_rows = self._value_rows(
                training_rows,
                field,
            )

            validation_value_rows = self._value_rows(
                validation_rows,
                field,
            )

            training_valid_rows = [
                row
                for _, row in training_value_rows
            ]

            baseline_accuracy = self._accuracy(
                training_valid_rows
            )

            best = self._best_threshold(
                training_value_rows
            )

            if best is None:
                components[field] = {
                    "sample_size": len(
                        training_valid_rows
                    ),
                    "training_sample_size": len(
                        training_valid_rows
                    ),
                    "validation_sample_size": len(
                        validation_value_rows
                    ),
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
                    "absolute_predictive_score_pct": 0.0,
                    "validation_passed": False,
                    "validation_reason": (
                        "NO_ACTIONABLE_TRAINING_THRESHOLD"
                    ),
                    "actionable": False,
                }
                continue

            validation = self._validate_threshold(
                validation_value_rows,
                best["threshold"],
                best["separation"],
            )

            high_lift = round(
                best["high_accuracy"]
                - baseline_accuracy,
                2,
            )

            actionable = bool(
                validation.get("validation_passed")
            )

            predictive_score = (
                best["separation"]
                if actionable
                else 0.0
            )

            components[field] = {
                "sample_size": len(
                    training_valid_rows
                ),
                "training_sample_size": len(
                    training_valid_rows
                ),
                "validation_sample_size": len(
                    validation_value_rows
                ),
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
                "predictive_score_pct": round(
                    predictive_score,
                    2,
                ),
                "absolute_predictive_score_pct": round(
                    abs(predictive_score),
                    2,
                ),
                **validation,
                "actionable": actionable,
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
                int(
                    data.get("sample_size")
                    or 0
                ),
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
            "raw_completed_sample_size": getattr(
                self,
                "last_raw_completed_count",
                len(rows),
            ),
            "deduped_sample_size": getattr(
                self,
                "last_deduped_count",
                len(rows),
            ),
            "conflicted_bucket_count": getattr(
                self,
                "last_conflicted_bucket_count",
                0,
            ),
            "graded_sample_size": len(rows),
            "training_sample_size": len(
                training_rows
            ),
            "validation_sample_size": len(
                validation_rows
            ),
            "holdout_ratio": self.HOLDOUT_RATIO,
            "components": components,
            "best_predictor": best_predictor,
            "worst_predictor": worst_predictor,
            "status": (
                "FORECAST_COMPONENT_ATTRIBUTION_READY"
            ),
        }
