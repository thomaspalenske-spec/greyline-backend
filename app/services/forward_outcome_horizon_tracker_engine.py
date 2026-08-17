import json
from app.services.time_utils import parse_utc
from datetime import datetime
from pathlib import Path


class ForwardOutcomeHorizonTrackerEngine:
    def __init__(self):
        self.memory_file = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")

    def _parse_dt(self, value):
        if not value:
            return None
        try:
            return parse_utc(value)
        except Exception:
            return None

    def _eligible_horizons(self, age_hours):
        return {
            "eligible_1h": age_hours >= 1,
            "eligible_4h": age_hours >= 4,
            "eligible_1d": age_hours >= 24,
            "eligible_3d": age_hours >= 72,
            "eligible_10d": age_hours >= 240,
        }

    def evaluate(self, limit=500):
        if not self.memory_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "record_count": 0,
                "status": "NO_OPPORTUNITY_MEMORY_FOR_HORIZON_TRACKING",
            }

        lines = self.memory_file.read_text().splitlines()
        records = [json.loads(x) for x in lines[-limit:] if x.strip()]

        now = datetime.utcnow()
        eligible_counts = {
            "eligible_1h": 0,
            "eligible_4h": 0,
            "eligible_1d": 0,
            "eligible_3d": 0,
            "eligible_10d": 0,
        }

        tracked = []

        for r in records:
            ts = self._parse_dt(r.get("timestamp"))
            if not ts:
                continue

            age_hours = round((now - ts).total_seconds() / 3600, 2)
            horizons = self._eligible_horizons(age_hours)

            for key, value in horizons.items():
                if value:
                    eligible_counts[key] += 1

            tracked.append({
                "symbol": r.get("symbol"),
                "directional_bias": r.get("directional_bias"),
                "candidate_result": r.get("result"),
                "score": r.get("score"),
                "snapshot_price": r.get("snapshot_price"),
                "age_hours": age_hours,
                **horizons,
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ForwardOutcomeHorizonTrackerEngine",
            "record_count": len(records),
            "eligible_counts": eligible_counts,
            "latest_tracked": tracked[-25:],
            "status": "FORWARD_OUTCOME_HORIZON_TRACKER_READY",
        }
