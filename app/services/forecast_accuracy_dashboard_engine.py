from pathlib import Path
import json
from datetime import datetime


class ForecastAccuracyDashboardEngine:
    def __init__(self):
        self.path = Path("app/data/forecast_outcome_grades.jsonl")

    def dashboard(self):
        grades = []

        if self.path.exists():
            with self.path.open() as f:
                for line in f:
                    try:
                        grades.append(json.loads(line))
                    except:
                        pass

        total = len(grades)

        pending = sum(
            1 for g in grades
            if g.get("forecast_correct") is None
        )

        correct = sum(
            1 for g in grades
            if g.get("forecast_correct") is True
        )

        accuracy = (
            round(correct / (total - pending) * 100, 2)
            if total > pending and total > 0
            else 0
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastAccuracyDashboardEngine",
            "total_forecasts": total,
            "pending_grades": pending,
            "graded_forecasts": total - pending,
            "correct_forecasts": correct,
            "accuracy_pct": accuracy,
            "status": "FORECAST_ACCURACY_DASHBOARD_READY",
        }
