import json
from datetime import datetime
from pathlib import Path


class ForecastComponentAttributionEngine:
    def __init__(self):
        self.path = Path("app/data/forecast_outcome_grades.jsonl")

    def evaluate(self, limit=500):
        if not self.path.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "engine": "ForecastComponentAttributionEngine",
                "components": {},
                "best_predictor": None,
                "worst_predictor": None,
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

        component_fields = [
            "regime_score",
            "risk_state_score",
            "breadth_score",
            "setup_score",
            "asymmetry_score",
            "volatility_score",
        ]

        components = {}

        for field in component_fields:
            total = 0
            correct = 0
            high_signal_total = 0
            high_signal_correct = 0

            for row in rows:
                value = row.get(field)

                try:
                    value = float(value)
                except Exception:
                    continue

                total += 1

                if row.get("forecast_correct") is True:
                    correct += 1

                if value >= 70:
                    high_signal_total += 1
                    if row.get("forecast_correct") is True:
                        high_signal_correct += 1

            accuracy = round((correct / total) * 100, 2) if total else 0
            high_signal_accuracy = round(
                (high_signal_correct / high_signal_total) * 100, 2
            ) if high_signal_total else 0

            components[field] = {
                "sample_size": total,
                "accuracy_pct": accuracy,
                "high_signal_sample_size": high_signal_total,
                "high_signal_accuracy_pct": high_signal_accuracy,
            }

        ranked = [
            (name, data["high_signal_accuracy_pct"], data["high_signal_sample_size"])
            for name, data in components.items()
            if data["high_signal_sample_size"] > 0
        ]

        ranked.sort(key=lambda x: x[1], reverse=True)

        best_predictor = ranked[0][0] if ranked else None
        worst_predictor = ranked[-1][0] if ranked else None

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastComponentAttributionEngine",
            "components": components,
            "best_predictor": best_predictor,
            "worst_predictor": worst_predictor,
            "status": "FORECAST_COMPONENT_ATTRIBUTION_READY",
        }
