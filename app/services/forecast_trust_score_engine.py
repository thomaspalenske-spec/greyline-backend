import json
from datetime import datetime
from pathlib import Path


class ForecastTrustScoreEngine:
    def __init__(self):
        self.file = Path("app/data/forecast_outcome_grades.jsonl")

    def evaluate(self):
        grades = []

        if self.file.exists():
            for line in self.file.read_text().splitlines():
                if not line.strip():
                    continue

                row = json.loads(line)

                if row.get("forecast_correct") is not None:
                    grades.append(row)

        sample_size = len(grades)

        if sample_size:
            correct = sum(
                1 for g in grades
                if g.get("forecast_correct") is True
            )
            accuracy = round(correct / sample_size * 100, 2)
        else:
            accuracy = 0.0

        if sample_size < 10:
            confidence = "INSUFFICIENT_DATA"
            multiplier = 1.0
        elif accuracy > 65:
            confidence = "HIGHLY_TRUSTED"
            multiplier = 1.2
        elif accuracy > 55:
            confidence = "TRUSTED"
            multiplier = 1.1
        elif accuracy >= 45:
            confidence = "NEUTRAL"
            multiplier = 1.0
        else:
            confidence = "DISTRUSTED"
            multiplier = 0.8

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastTrustScoreEngine",
            "trust_score": accuracy,
            "sample_size": sample_size,
            "accuracy_pct": accuracy,
            "confidence_level": confidence,
            "deployment_multiplier": multiplier,
            "status": "FORECAST_TRUST_SCORE_READY",
        }
