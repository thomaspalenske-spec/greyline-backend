import json
from datetime import datetime
from pathlib import Path


class OperatorNotificationEngine:
    """
    Persistent operator notification ledger.
    Records events GreyLine should not let disappear silently.
    """

    def __init__(self):
        self.ledger_file = Path("app/data/operator_notifications/operator_notifications.jsonl")
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)

    def _read(self):
        if not self.ledger_file.exists():
            return []
        rows = []
        for line in self.ledger_file.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        return rows

    def _write(self, rows):
        self.ledger_file.write_text(
            "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else "")
        )

    def record(self, event_type, title, message, severity="INFO", source="GREYLINE", payload=None):
        payload = payload or {}
        notification_id = f"{event_type}-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"

        row = {
            "notification_id": notification_id,
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "title": title,
            "message": message,
            "severity": severity,
            "source": source,
            "payload": payload,
            "acknowledged": False,
            "acknowledged_at": None,
        }

        with self.ledger_file.open("a") as f:
            f.write(json.dumps(row) + "\n")

        return {
            "notification_recorded": True,
            "notification": row,
            "status": "OPERATOR_NOTIFICATION_RECORDED",
        }

    def unread(self):
        rows = [r for r in self._read() if r.get("acknowledged") is not True]
        rows = sorted(rows, key=lambda r: r.get("timestamp") or "", reverse=True)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "OperatorNotificationEngine",
            "unread_count": len(rows),
            "notifications": rows[:50],
            "status": "OPERATOR_NOTIFICATIONS_READY",
        }

    def acknowledge(self, notification_id):
        rows = self._read()
        matched = False

        for r in rows:
            if r.get("notification_id") == notification_id:
                r["acknowledged"] = True
                r["acknowledged_at"] = datetime.utcnow().isoformat()
                matched = True

        if matched:
            self._write(rows)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "notification_id": notification_id,
            "acknowledged": matched,
            "status": "OPERATOR_NOTIFICATION_ACKNOWLEDGED" if matched else "OPERATOR_NOTIFICATION_NOT_FOUND",
        }
