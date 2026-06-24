import json
from datetime import datetime
from pathlib import Path


class ForecastFeedbackEngine:
    def __init__(self):
        self.path = Path("app/data/forecast_outcome_grades.jsonl")

    def evaluate(self, limit=100):
        if not self.path.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "engine": "ForecastFeedbackEngine",
                "graded_count": 0,
                "feedback": "INSUFFICIENT_DATA",
                "confidence_adjustment": "HOLD",
                "status": "NO_FORECAST_GRADES",
            }

        rows = []
        for line in self.path.read_text().splitlines()[-limit:]:
            try:
                row = json.loads(line)
                if row.get("forecast_correct") is not None:
                    rows.append(row)
            except Exception:
                pass

        graded_count = len(rows)
        correct_count = sum(1 for r in rows if r.get("forecast_correct") is True)

        accuracy_pct = round((correct_count / graded_count) * 100, 2) if graded_count else 0

        if graded_count < 10:
            feedback = "INSUFFICIENT_MATURE_SAMPLE"
            adjustment = "HOLD"
        elif accuracy_pct >= 65:
            feedback = "FORECAST_CONFIDENCE_STRENGTHENING"
            adjustment = "INCREASE_CONFIDENCE"
        elif accuracy_pct <= 45:
            feedback = "FORECAST_CONFIDENCE_WEAKENING"
            adjustment = "REDUCE_CONFIDENCE"
        else:
            feedback = "FORECAST_CONFIDENCE_STABLE"
            adjustment = "HOLD"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastFeedbackEngine",
            "graded_count": graded_count,
            "correct_count": correct_count,
            "accuracy_pct": accuracy_pct,
            "feedback": feedback,
            "confidence_adjustment": adjustment,
            "status": "FORECAST_FEEDBACK_READY",
        }
