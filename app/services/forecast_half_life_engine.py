import json
from app.services.time_utils import parse_utc
from datetime import datetime
from pathlib import Path


class ForecastHalfLifeEngine:
    """
    Time-decays historical forecast performance so
    recent forecasts influence learning more than
    old forecasts.
    """

    def __init__(self):
        self.path = Path("app/data/forecast_outcome_grades.jsonl")

    def _age_days(self, ts):
        try:
            dt = parse_utc(ts)
            return max(
                0,
                (datetime.utcnow() - dt).total_seconds() / 86400,
            )
        except Exception:
            return None

    def _weight(self, age):

        if age is None:
            return 0.25

        if age <= 7:
            return 1.00

        if age <= 30:
            return 0.90

        if age <= 90:
            return 0.75

        if age <= 180:
            return 0.55

        if age <= 365:
            return 0.30

        return 0.10

    def evaluate(self):

        if not self.path.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "engine": "ForecastHalfLifeEngine",
                "weighted_accuracy_pct": None,
                "sample_size": 0,
                "status": "NO_FORECAST_HISTORY",
            }

        weighted_hits = 0.0
        weighted_total = 0.0
        rows = 0

        for line in self.path.read_text().splitlines():

            if not line.strip():
                continue

            try:
                row = json.loads(line)
            except Exception:
                continue

            if row.get("forecast_correct") is None:
                continue

            rows += 1

            age = self._age_days(
                row.get("forecast_timestamp")
                or row.get("timestamp")
            )

            w = self._weight(age)

            weighted_total += w

            if row.get("forecast_correct"):
                weighted_hits += w

        accuracy = None

        if weighted_total:
            accuracy = round(
                weighted_hits /
                weighted_total *
                100,
                2,
            )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastHalfLifeEngine",
            "sample_size": rows,
            "weighted_accuracy_pct": accuracy,
            "total_weight": round(weighted_total, 3),
            "status": "FORECAST_HALF_LIFE_READY",
        }
