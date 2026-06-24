import json
from datetime import datetime
from pathlib import Path


class ForecastRegimeAttributionEngine:
    def __init__(self):
        self.file = Path("app/data/forecast_outcome_grades.jsonl")

    def evaluate(self, limit=500):
        if not self.file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "NO_FORECAST_GRADE_DATA",
            }

        rows = [
            json.loads(x)
            for x in self.file.read_text().splitlines()[-limit:]
            if x.strip()
        ]

        regimes = {}

        for row in rows:
            if row.get("forecast_correct") is None:
                continue

            regime = row.get("regime", "UNKNOWN")

            bucket = regimes.setdefault(
                regime,
                {"total": 0, "correct": 0}
            )

            bucket["total"] += 1

            if row.get("forecast_correct") is True:
                bucket["correct"] += 1

        summary = {}

        for regime, stats in regimes.items():
            total = stats["total"]
            correct = stats["correct"]

            summary[regime] = {
                "sample_size": total,
                "correct": correct,
                "accuracy_pct": round(
                    (correct / total) * 100, 2
                ) if total else 0
            }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastRegimeAttributionEngine",
            "regimes": summary,
            "status": "FORECAST_REGIME_ATTRIBUTION_READY",
        }
