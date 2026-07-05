import json
from datetime import datetime, timedelta
from pathlib import Path

from app.services.operator_notification_engine import OperatorNotificationEngine
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class OperatorEventBusEngine:
    """
    Standard event bus for operator-visible GreyLine events.
    One publish point. Many downstream consumers.
    """

    def __init__(self):
        self.ledger_file = Path("app/data/operator_events/operator_events.jsonl")
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)

    def publish(
        self,
        source="GREYLINE",
        category="SYSTEM",
        severity="INFO",
        title="GreyLine Event",
        message="",
        symbol=None,
        trade_id=None,
        ack_required=False,
        payload=None,
    ):
        payload = payload or {}

        dedupe_key = "|".join([
            str(source),
            str(category),
            str(symbol),
            str(title),
            str(message),
        ])
        dedupe_window_seconds = int(payload.get("dedupe_window_seconds") or 60)

        recent_duplicate = self._recent_duplicate(dedupe_key, dedupe_window_seconds)
        if recent_duplicate:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "engine": "OperatorEventBusEngine",
                "event_published": False,
                "deduped": True,
                "dedupe_key": dedupe_key,
                "duplicate_of_event_id": recent_duplicate.get("event_id"),
                "status": "OPERATOR_EVENT_DEDUPED",
            }

        event_id = f"{source}-{category}-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"

        event = {
            "event_id": event_id,
            "timestamp": datetime.utcnow().isoformat(),
            "source": source,
            "category": category,
            "severity": severity,
            "title": title,
            "message": message,
            "symbol": symbol,
            "trade_id": trade_id,
            "ack_required": bool(ack_required),
            "payload": payload,
            "dedupe_key": dedupe_key,
        }

        with self.ledger_file.open("a") as f:
            f.write(json.dumps(event) + "\n")

        notification = None
        if ack_required or severity in ["CRITICAL", "WARNING"]:
            notification = OperatorNotificationEngine().record(
                event_type=category,
                title=title,
                message=message,
                severity=severity,
                source=source,
                payload=event,
            )

        audit = ImmutableAuditLedgerEngine().record("OPERATOR_EVENT_PUBLISHED", event)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "OperatorEventBusEngine",
            "event_published": True,
            "event": event,
            "notification": notification,
            "audit": audit,
            "status": "OPERATOR_EVENT_PUBLISHED",
        }


    def _recent_duplicate(self, dedupe_key, window_seconds=60):
        if not self.ledger_file.exists():
            return None

        cutoff = datetime.utcnow() - timedelta(seconds=window_seconds)

        for line in reversed(self.ledger_file.read_text().splitlines()):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue

            if row.get("dedupe_key") != dedupe_key:
                continue

            try:
                row_time = datetime.fromisoformat(row.get("timestamp"))
            except Exception:
                continue

            if row_time >= cutoff:
                return row

        return None

    def recent(self, limit=50):
        if not self.ledger_file.exists():
            rows = []
        else:
            rows = []
            for line in self.ledger_file.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue

        rows = sorted(rows, key=lambda r: r.get("timestamp") or "", reverse=True)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "OperatorEventBusEngine",
            "event_count": len(rows),
            "events": rows[:limit],
            "status": "OPERATOR_EVENTS_READY",
        }
