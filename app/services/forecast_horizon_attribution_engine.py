import json
from datetime import datetime
from pathlib import Path


class ForecastHorizonAttributionEngine:
    def __init__(self):
        self.path = Path("app/data/forecast_outcome_grades.jsonl")

    def evaluate(self, limit=500):
        if not self.path.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "engine": "ForecastHorizonAttributionEngine",
                "horizons": {},
                "best_horizon": None,
                "status": "NO_FORECAST_GRADE_DATA",
            }

        rows = []
        for line in self.path.read_text().splitlines()[-limit:]:
            try:
                row = json.loads(line)
                if row.get("forecast_correct") is not None:
                    rows.append(row)
            except Exception:
                pass

        horizons = {
            "15m": {"min": 15, "max": 30, "total": 0, "correct": 0},
            "30m": {"min": 30, "max": 60, "total": 0, "correct": 0},
            "1h": {"min": 60, "max": 240, "total": 0, "correct": 0},
            "4h": {"min": 240, "max": 1440, "total": 0, "correct": 0},
            "1d": {"min": 1440, "max": 10080, "total": 0, "correct": 0},
        }

        for row in rows:
            age = row.get("forecast_age_minutes")
            try:
                age = float(age)
            except Exception:
                continue

            for name, bucket in horizons.items():
                if bucket["min"] <= age < bucket["max"]:
                    bucket["total"] += 1
                    if row.get("forecast_correct") is True:
                        bucket["correct"] += 1

        horizon_summary = {}
        best_horizon = None
        best_accuracy = -1

        for name, bucket in horizons.items():
            total = bucket["total"]
            correct = bucket["correct"]
            accuracy = round((correct / total) * 100, 2) if total else 0

            horizon_summary[name] = {
                "sample_size": total,
                "correct": correct,
                "accuracy_pct": accuracy,
            }

            if total > 0 and accuracy > best_accuracy:
                best_accuracy = accuracy
                best_horizon = name

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastHorizonAttributionEngine",
            "horizons": horizon_summary,
            "best_horizon": best_horizon,
            "status": "FORECAST_HORIZON_ATTRIBUTION_READY",
        }
