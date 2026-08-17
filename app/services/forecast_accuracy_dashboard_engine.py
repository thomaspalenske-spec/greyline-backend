from pathlib import Path
import json
from datetime import datetime


class ForecastAccuracyDashboardEngine:
    def __init__(self):
        self.path = Path("app/data/forecast_outcome_grades.jsonl")

    def dashboard(self):
        grades = []
        skipped_lines = 0

        if self.path.exists():
            with self.path.open() as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        grades.append(json.loads(line))
                    except json.JSONDecodeError:
                        # a corrupt ledger line is COUNTED, not silently swallowed by a bare `except`
                        # (which also ate KeyboardInterrupt/SystemExit) — surface it below.
                        skipped_lines += 1

        total = len(grades)

        pending = sum(
            1 for g in grades
            if g.get("forecast_correct") is None
        )

        correct = sum(
            1 for g in grades
            if g.get("forecast_correct") is True
        )

        graded = total - pending
        # None (n/a) when nothing is graded yet — a real 0% accuracy and "no sample yet" are different
        # states; returning 0 for both painted an ungraded engine as 0% correct.
        accuracy = round(correct / graded * 100, 2) if graded > 0 else None

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastAccuracyDashboardEngine",
            "total_forecasts": total,
            "pending_grades": pending,
            "graded_forecasts": graded,
            "correct_forecasts": correct,
            "accuracy_pct": accuracy,
            "skipped_corrupt_lines": skipped_lines,
            "status": ("FORECAST_ACCURACY_DASHBOARD_DEGRADED" if skipped_lines
                       else "FORECAST_ACCURACY_DASHBOARD_READY"),
        }
