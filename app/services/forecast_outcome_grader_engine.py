from datetime import datetime
import json
from pathlib import Path


class ForecastOutcomeGraderEngine:
    def __init__(self):
        self.outcome_path = Path("app/data/forecast_outcomes.jsonl")
        self.graded_path = Path("app/data/forecast_outcome_grades.jsonl")

    def _read_outcomes(self):
        if not self.outcome_path.exists():
            return []

        rows = []
        with self.outcome_path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def grade_pending(self, market_prices=None):
        market_prices = market_prices or {}
        outcomes = self._read_outcomes()
        graded = []

        for record in outcomes[-25:]:
            symbol = record.get("symbol")
            predicted_direction = record.get("predicted_direction")
            predicted_score = record.get("predicted_score")

            current_price = market_prices.get(symbol)

            grade_record = {
                "timestamp": datetime.utcnow().isoformat(),
                "forecast_id": record.get("forecast_id"),
                "symbol": symbol,
                "predicted_direction": predicted_direction,
                "predicted_score": predicted_score,
                "current_price": current_price,
                "forecast_grade": "PENDING_MARKET_PRICE",
                "forecast_correct": None,
                "status": "FORECAST_OUTCOME_GRADE_PENDING",
            }

            graded.append(grade_record)

        self.graded_path.parent.mkdir(parents=True, exist_ok=True)
        with self.graded_path.open("w") as f:
            for row in graded:
                f.write(json.dumps(row) + "\n")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastOutcomeGraderEngine",
            "graded_count": len(graded),
            "grades": graded,
            "status": "FORECAST_OUTCOME_GRADER_READY",
        }
