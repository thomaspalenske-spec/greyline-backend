import json
from datetime import datetime
from pathlib import Path


class ForecastMetaLearningEngine:
    def __init__(self):
        self.path = Path("app/data/forecast_outcome_grades.jsonl")

    def _score_band(self, score):
        try:
            score = float(score)
        except Exception:
            return "UNKNOWN"

        if score >= 90:
            return "90_PLUS"
        if score >= 85:
            return "85_90"
        if score >= 80:
            return "80_85"
        if score >= 75:
            return "75_80"
        if score >= 70:
            return "70_75"
        return "BELOW_70"

    def _best_bucket(self, buckets):
        best_name = None
        best_accuracy = -1
        best_sample = 0

        for name, stats in buckets.items():
            total = stats["total"]
            correct = stats["correct"]
            accuracy = round((correct / total) * 100, 2) if total else 0

            stats["accuracy_pct"] = accuracy
            stats["sample_size"] = total

            if total > 0 and accuracy > best_accuracy:
                best_name = name
                best_accuracy = accuracy
                best_sample = total

        return best_name, best_accuracy if best_accuracy >= 0 else 0, best_sample

    def evaluate(self, limit=500):
        rows = []

        if self.path.exists():
            for line in self.path.read_text().splitlines()[-limit:]:
                try:
                    row = json.loads(line)
                    if row.get("forecast_correct") is not None:
                        rows.append(row)
                except Exception:
                    pass

        buckets = {
            "score_band": {},
            "direction": {},
            "confidence": {},
            "regime": {},
        }

        for row in rows:
            correct = row.get("forecast_correct") is True

            values = {
                "score_band": self._score_band(row.get("predicted_score")),
                "direction": row.get("predicted_direction") or "UNKNOWN",
                "confidence": row.get("confidence") or row.get("forecast_confidence") or "UNKNOWN",
                "regime": row.get("regime") or "UNKNOWN",
            }

            for category, value in values.items():
                bucket = buckets[category].setdefault(value, {"total": 0, "correct": 0})
                bucket["total"] += 1
                if correct:
                    bucket["correct"] += 1

        best = {}
        for category, data in buckets.items():
            name, accuracy, sample = self._best_bucket(data)
            best[category] = {
                "best_value": name,
                "accuracy_pct": accuracy,
                "sample_size": sample,
                "buckets": data,
            }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastMetaLearningEngine",
            "graded_sample_size": len(rows),
            "best_score_band": best["score_band"]["best_value"],
            "best_direction": best["direction"]["best_value"],
            "best_confidence": best["confidence"]["best_value"],
            "best_regime": best["regime"]["best_value"],
            "meta_learning": best,
            "status": "FORECAST_META_LEARNING_READY",
        }
