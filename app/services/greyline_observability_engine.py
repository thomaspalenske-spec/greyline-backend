from datetime import datetime


class GreyLineObservabilityEngine:

    def __init__(self):

        self.logs = []

    def emit(self, source, event_type, data):

        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": source,
            "event_type": event_type,
            "data": data
        }

        self.logs.append(event)

        return event

    def get_logs(self, event_type=None):

        if event_type:
            return [e for e in self.logs if e["event_type"] == event_type]

        return self.logs

    def health_snapshot(self):

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "log_count": len(self.logs),
            "status": "OBSERVABILITY_ACTIVE"
        }
