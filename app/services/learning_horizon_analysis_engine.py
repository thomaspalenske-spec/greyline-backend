import json
from app.services.time_utils import parse_utc
from datetime import datetime
from pathlib import Path


class LearningHorizonAnalysisEngine:
    def __init__(self):
        self.memory_file = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")

    def _parse_dt(self, value):
        if not value:
            return None
        try:
            return parse_utc(value)
        except Exception:
            return None

    def analyze(self, limit=500):
        if not self.memory_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "record_count": 0,
                "status": "NO_OPPORTUNITY_MEMORY_FOR_HORIZON_ANALYSIS",
            }

        lines = self.memory_file.read_text().splitlines()
        records = [json.loads(x) for x in lines[-limit:] if x.strip()]

        now = datetime.utcnow()
        buckets = {
            "too_fresh_under_1h": 0,
            "one_to_four_hours": 0,
            "four_to_24_hours": 0,
            "one_to_three_days": 0,
            "three_to_10_days": 0,
            "older_than_10_days": 0,
            "unknown_age": 0,
        }

        for r in records:
            ts = self._parse_dt(r.get("timestamp"))
            if not ts:
                buckets["unknown_age"] += 1
                continue

            age_hours = (now - ts).total_seconds() / 3600

            if age_hours < 1:
                buckets["too_fresh_under_1h"] += 1
            elif age_hours < 4:
                buckets["one_to_four_hours"] += 1
            elif age_hours < 24:
                buckets["four_to_24_hours"] += 1
            elif age_hours < 72:
                buckets["one_to_three_days"] += 1
            elif age_hours < 240:
                buckets["three_to_10_days"] += 1
            else:
                buckets["older_than_10_days"] += 1

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "LearningHorizonAnalysisEngine",
            "record_count": len(records),
            "horizon_buckets": buckets,
            "analysis_note": "Phase 1 classifies candidate age. Phase 2 will attach 1h/4h/1d/3d/10d return outcomes.",
            "status": "LEARNING_HORIZON_ANALYSIS_READY",
        }
