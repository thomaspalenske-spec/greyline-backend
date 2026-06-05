import json
from datetime import datetime
from pathlib import Path


class LiveMonitoringHistoryEngine:

    def __init__(self):
        self.log_file = Path("app/data/live_monitoring/live_monitoring_events.jsonl")

    def get_history(self, limit=20):
        if not self.log_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "events_found": False,
                "events": [],
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "NO_LIVE_MONITORING_HISTORY_FOUND"
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
            "status": "LIVE_MONITORING_HISTORY_READY"
        }
