from datetime import datetime

from app.services.forecast_component_attribution_engine import (
    ForecastComponentAttributionEngine,
)


class ForecastWalkForwardValidationEngine:
    VALIDATION_SIZE = 40
    MIN_TRAINING_SIZE = 60
    MIN_FOLD_COUNT = 3
    MIN_PASS_RATIO = 0.60
    MIN_VALIDATION_BUCKET_SAMPLE = 5

    def __init__(self):
        self.attribution_engine = (
            ForecastComponentAttributionEngine()
        )

    def _validate(
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

        high_accuracy = (
            self.attribution_engine._accuracy(
                high_rows
            )
        )

        low_accuracy = (
            self.attribution_engine._accuracy(
                low_rows
            )
        )

        validation_separation = round(
            high_accuracy - low_accuracy,
            2,
        )

        enough_samples = bool(
            len(high_rows)
            >= self.MIN_VALIDATION_BUCKET_SAMPLE
            and len(low_rows)
            >= self.MIN_VALIDATION_BUCKET_SAMPLE
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

        passed = bool(
            enough_samples
            and same_direction
        )

        return {
            "validation_high_sample_size": len(
                high_rows
            ),
            "validation_low_sample_size": len(
                low_rows
            ),
            "validation_high_accuracy_pct": (
                high_accuracy
            ),
            "validation_low_accuracy_pct": (
                low_accuracy
            ),
            "validation_separation_pct": (
                validation_separation
            ),
            "enough_validation_samples": (
                enough_samples
            ),
            "direction_confirmed": same_direction,
            "passed": passed,
        }

    def evaluate(self, limit=500):
        rows = self.attribution_engine._load_rows(
            limit
        )

        fields = list(
            self.attribution_engine.COMPONENT_FIELDS
        )

        fold_results = []

        validation_end = len(rows)

        while True:
            validation_start = (
                validation_end
                - self.VALIDATION_SIZE
            )

            if (
                validation_start
                < self.MIN_TRAINING_SIZE
            ):
                break

            training_rows = rows[
                :validation_start
            ]

            validation_rows = rows[
                validation_start:validation_end
            ]

            components = {}

            for field in fields:
                training_value_rows = (
                    self.attribution_engine
                    ._value_rows(
                        training_rows,
                        field,
                    )
                )

                validation_value_rows = (
                    self.attribution_engine
                    ._value_rows(
                        validation_rows,
                        field,
                    )
                )

                best = (
                    self.attribution_engine
                    ._best_threshold(
                        training_value_rows
                    )
                )

                if best is None:
                    components[field] = {
                        "selected_threshold": None,
                        "training_separation_pct": 0.0,
                        "validation_separation_pct": 0.0,
                        "passed": False,
                        "reason": (
                            "NO_ACTIONABLE_TRAINING_THRESHOLD"
                        ),
                    }
                    continue

                validation = self._validate(
                    validation_value_rows,
                    best["threshold"],
                    best["separation"],
                )

                components[field] = {
                    "selected_threshold": best[
                        "threshold"
                    ],
                    "training_high_sample_size": len(
                        best["high_rows"]
                    ),
                    "training_low_sample_size": len(
                        best["low_rows"]
                    ),
                    "training_high_accuracy_pct": (
                        best["high_accuracy"]
                    ),
                    "training_low_accuracy_pct": (
                        best["low_accuracy"]
                    ),
                    "training_separation_pct": (
                        best["separation"]
                    ),
                    **validation,
                    "reason": (
                        "WALK_FORWARD_FOLD_PASSED"
                        if validation["passed"]
                        else "WALK_FORWARD_FOLD_FAILED"
                    ),
                }

            fold_results.append({
                "fold_number": len(
                    fold_results
                ) + 1,
                "training_size": len(
                    training_rows
                ),
                "validation_size": len(
                    validation_rows
                ),
                "training_start": (
                    self.attribution_engine
                    ._forecast_time(
                        training_rows[0]
                    )
                    if training_rows
                    else None
                ),
                "training_end": (
                    self.attribution_engine
                    ._forecast_time(
                        training_rows[-1]
                    )
                    if training_rows
                    else None
                ),
                "validation_start": (
                    self.attribution_engine
                    ._forecast_time(
                        validation_rows[0]
                    )
                    if validation_rows
                    else None
                ),
                "validation_end": (
                    self.attribution_engine
                    ._forecast_time(
                        validation_rows[-1]
                    )
                    if validation_rows
                    else None
                ),
                "components": components,
            })

            validation_end = validation_start

        fold_results.reverse()

        predictor_summary = {}

        for field in fields:
            field_folds = [
                (
                    fold.get("components")
                    or {}
                ).get(field) or {}
                for fold in fold_results
            ]

            evaluated_folds = [
                row
                for row in field_folds
                if row.get(
                    "selected_threshold"
                ) is not None
            ]

            passed_folds = [
                row
                for row in evaluated_folds
                if row.get("passed") is True
            ]

            positive_passes = sum(
                1
                for row in passed_folds
                if float(
                    row.get(
                        "validation_separation_pct"
                    )
                    or 0.0
                ) > 0
            )

            negative_passes = sum(
                1
                for row in passed_folds
                if float(
                    row.get(
                        "validation_separation_pct"
                    )
                    or 0.0
                ) < 0
            )

            evaluated_count = len(
                evaluated_folds
            )

            pass_count = len(passed_folds)

            pass_ratio = (
                pass_count / evaluated_count
                if evaluated_count
                else 0.0
            )

            dominant_direction = (
                "POSITIVE"
                if positive_passes
                > negative_passes
                else "NEGATIVE"
                if negative_passes
                > positive_passes
                else "MIXED"
            )

            direction_consistent = bool(
                pass_count > 0
                and (
                    positive_passes
                    == pass_count
                    or negative_passes
                    == pass_count
                )
            )

            qualified = bool(
                len(fold_results)
                >= self.MIN_FOLD_COUNT
                and evaluated_count
                >= self.MIN_FOLD_COUNT
                and pass_ratio
                >= self.MIN_PASS_RATIO
                and direction_consistent
            )

            predictor_summary[field] = {
                "total_fold_count": len(
                    fold_results
                ),
                "evaluated_fold_count": (
                    evaluated_count
                ),
                "passed_fold_count": pass_count,
                "failed_fold_count": (
                    evaluated_count
                    - pass_count
                ),
                "pass_ratio": round(
                    pass_ratio,
                    4,
                ),
                "positive_pass_count": (
                    positive_passes
                ),
                "negative_pass_count": (
                    negative_passes
                ),
                "dominant_direction": (
                    dominant_direction
                ),
                "direction_consistent": (
                    direction_consistent
                ),
                "qualified": qualified,
            }

        qualified_predictors = [
            field
            for field, summary
            in predictor_summary.items()
            if summary.get("qualified") is True
        ]

        return {
            "timestamp": (
                datetime.utcnow().isoformat()
            ),
            "engine": (
                "ForecastWalkForwardValidationEngine"
            ),
            "raw_completed_sample_size": getattr(
                self.attribution_engine,
                "last_raw_completed_count",
                len(rows),
            ),
            "deduped_sample_size": len(rows),
            "validation_size_per_fold": (
                self.VALIDATION_SIZE
            ),
            "minimum_training_size": (
                self.MIN_TRAINING_SIZE
            ),
            "minimum_fold_count": (
                self.MIN_FOLD_COUNT
            ),
            "minimum_pass_ratio": (
                self.MIN_PASS_RATIO
            ),
            "fold_count": len(fold_results),
            "folds": fold_results,
            "predictor_summary": (
                predictor_summary
            ),
            "qualified_predictors": (
                qualified_predictors
            ),
            "status": (
                "WALK_FORWARD_READY"
                if len(fold_results)
                >= self.MIN_FOLD_COUNT
                else "INSUFFICIENT_WALK_FORWARD_FOLDS"
            ),
        }
