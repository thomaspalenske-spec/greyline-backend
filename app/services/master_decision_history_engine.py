import json
from datetime import datetime
from pathlib import Path
from app.services.ttl_cache import ttl_cached


class MasterDecisionHistoryEngine:

    def __init__(self):
        self.log_file = Path("app/data/master_decisions/master_decision_events.jsonl")

    @ttl_cached(30, env_key="GREYLINE_SHADOW_CACHE_TTL")
    def get_history(self, limit=20):
        if not self.log_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "events_found": False,
                "event_count": 0,
                "events": [],
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "NO_MASTER_DECISION_HISTORY_FOUND"
            }

        lines = self.log_file.read_text().splitlines()
        recent_lines = lines[-limit:]

        events = []
        for line in recent_lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "events_found": len(events) > 0,
            "event_count": len(events),
            "events": events,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "MASTER_DECISION_HISTORY_READY"
        }
