from datetime import datetime
import json
from pathlib import Path


class ForecastOutcomeCaptureEngine:
    def __init__(self):
        self.outcome_path = Path("app/data/forecast_outcomes.jsonl")

    def capture(self, forecast):
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "forecast_id": forecast.get("forecast_id") or forecast.get("timestamp"),
            "symbol": forecast.get("symbol"),
            "predicted_direction": forecast.get("directional_bias"),
            "predicted_score": forecast.get("composite_score") or forecast.get("score"),
            "forecast_timestamp": forecast.get("timestamp"),
            "status": "FORECAST_OUTCOME_CAPTURED_PENDING_MARKET_RESULT",
        }

        self.outcome_path.parent.mkdir(parents=True, exist_ok=True)

        with self.outcome_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

        return record
