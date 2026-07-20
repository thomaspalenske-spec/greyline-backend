import json
from app.services.time_utils import parse_utc
from datetime import datetime
from pathlib import Path


class SignalMaturityEngine:
    def __init__(self):
        self.memory_file = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")

    def _parse_dt(self, value):
        if not value:
            return None
        try:
            return parse_utc(value)
        except Exception:
            return None

    def _maturity_state(self, age_hours):
        if age_hours < 1:
            return "TOO_FRESH"
        if age_hours < 4:
            return "EARLY_SIGNAL"
        if age_hours < 72:
            return "MATURE_SIGNAL"
        if age_hours < 240:
            return "AGING_SIGNAL"
        return "EXPIRED_SIGNAL"

    def evaluate(self, limit=500):
        if not self.memory_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "record_count": 0,
                "status": "NO_SIGNAL_MEMORY_AVAILABLE",
            }

        lines = self.memory_file.read_text().splitlines()
        records = [json.loads(x) for x in lines[-limit:] if x.strip()]

        now = datetime.utcnow()
        states = {}
        examples = []

        for r in records:
            ts = self._parse_dt(r.get("timestamp"))
            if not ts:
                state = "UNKNOWN_AGE"
                age_hours = None
            else:
                age_hours = round((now - ts).total_seconds() / 3600, 2)
                state = self._maturity_state(age_hours)

            states[state] = states.get(state, 0) + 1

            examples.append({
                "symbol": r.get("symbol"),
                "directional_bias": r.get("directional_bias"),
                "candidate_result": r.get("result"),
                "score": r.get("score"),
                "snapshot_price": r.get("snapshot_price"),
                "age_hours": age_hours,
                "maturity_state": state,
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "SignalMaturityEngine",
            "record_count": len(records),
            "maturity_counts": states,
            "latest_signals": examples[-25:],
            "status": "SIGNAL_MATURITY_READY",
        }
