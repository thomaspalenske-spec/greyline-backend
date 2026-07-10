import json
from datetime import datetime
from pathlib import Path


class ForecastCalibrationEngine:
    """
    Learns whether forecast confidence is well calibrated.

    Example:
        90% confidence predictions should be correct ~90% of the time.

    Produces reliability statistics by confidence bucket.
    """

    def __init__(self):
        self.path = Path("app/data/forecast_outcome_grades.jsonl")

    @staticmethod
    def _bucket(conf):
        try:
            conf = float(conf)
        except Exception:
            return "UNKNOWN"

        if conf >= 90:
            return "90-100"
        if conf >= 80:
            return "80-89"
        if conf >= 70:
            return "70-79"
        if conf >= 60:
            return "60-69"
        return "<60"

    def evaluate(self, limit=1000):

        rows = []

        if self.path.exists():
            for line in self.path.read_text().splitlines()[-limit:]:
                try:
                    r = json.loads(line)
                    if r.get("forecast_correct") is not None:
                        rows.append(r)
                except Exception:
                    pass

        buckets = {}

        for row in rows:

            confidence = (
                row.get("institutional_calibrated_forecast_confidence")
                or row.get("institutional_forecast_confidence")
                or row.get("forecast_confidence")
                or row.get("confidence")
            )

            bucket = self._bucket(confidence)

            b = buckets.setdefault(
                bucket,
                {
                    "sample_size": 0,
                    "correct": 0,
                },
            )

            b["sample_size"] += 1

            if row.get("forecast_correct") is True:
                b["correct"] += 1

        reliability = {}

        total_error = 0
        bucket_count = 0

        expected_lookup = {
            "90-100": 95,
            "80-89": 85,
            "70-79": 75,
            "60-69": 65,
            "<60": 50,
        }

        unknown_confidence_count = 0

        for bucket, data in buckets.items():

            n = data["sample_size"]

            acc = round(
                data["correct"] / n * 100,
                2,
            ) if n else 0

            expected = expected_lookup.get(bucket)

            if expected is None:
                unknown_confidence_count += n
                reliability[bucket] = {
                    "sample_size": n,
                    "observed_accuracy_pct": acc,
                    "expected_accuracy_pct": None,
                    "calibration_error_pct": None,
                    "included_in_calibration": False,
                }
                continue

            calibration_error = round(
                abs(acc - expected),
                2,
            )

            reliability[bucket] = {
                "sample_size": n,
                "observed_accuracy_pct": acc,
                "expected_accuracy_pct": expected,
                "calibration_error_pct": calibration_error,
                "included_in_calibration": True,
            }

            total_error += calibration_error
            bucket_count += 1

        overall_error=round(
            total_error/bucket_count,
            2
        ) if bucket_count else None

        if overall_error is None:
            calibration_state="INSUFFICIENT_DATA"
        elif overall_error<=5:
            calibration_state="EXCELLENT"
        elif overall_error<=10:
            calibration_state="GOOD"
        elif overall_error<=20:
            calibration_state="FAIR"
        else:
            calibration_state="POOR"

        return {
            "timestamp":datetime.utcnow().isoformat(),
            "engine":"ForecastCalibrationEngine",
            "graded_sample_size": len(rows),
            "calibrated_sample_size": (
                len(rows) - unknown_confidence_count
            ),
            "unknown_confidence_count": (
                unknown_confidence_count
            ),
            "overall_calibration_error_pct": overall_error,
            "calibration_state":calibration_state,
            "reliability_curve":reliability,
            "status":"FORECAST_CALIBRATION_READY",
        }
