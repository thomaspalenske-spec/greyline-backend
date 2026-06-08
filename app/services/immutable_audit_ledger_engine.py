import json
from datetime import datetime
from pathlib import Path


class ImmutableAuditLedgerEngine:

    def __init__(self):
        self.audit_dir = Path("app/data/audit")
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        self.audit_file = self.audit_dir / "immutable_audit_ledger.jsonl"

    def record(self, event_type, payload):
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "payload": payload,
            "immutable": True,
        }

        with self.audit_file.open("a") as f:
            f.write(json.dumps(event) + "\n")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "event_recorded": True,
            "event_type": event_type,
            "status": "AUDIT_EVENT_RECORDED",
        }

    def history(self, limit=100):
        if not self.audit_file.exists():
            return {
                "events_found": False,
                "event_count": 0,
                "events": [],
                "status": "NO_AUDIT_EVENTS_FOUND",
            }

        lines = self.audit_file.read_text().splitlines()

        events = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except Exception:
                pass

        return {
            "events_found": True,
            "event_count": len(events),
            "events": events,
            "status": "AUDIT_LEDGER_READY",
        }

    def summary(self):
        history = self.history(limit=10000)

        counts = {}

        for event in history.get("events", []):
            event_type = event.get("event_type")
            counts[event_type] = counts.get(event_type, 0) + 1

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "IMMUTABLE_AUDIT_LEDGER",
            "event_count": history.get("event_count", 0),
            "event_type_counts": counts,
            "status": "AUDIT_LEDGER_SUMMARY_READY",
        }
