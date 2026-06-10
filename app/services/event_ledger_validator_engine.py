from datetime import datetime


class EventLedgerValidatorEngine:

    REQUIRED_FIELDS = [
        "trade_id",
        "event_type",
        "timestamp",
        "payload"
    ]

    VALID_EVENT_TYPES = {
        "trade_created",
        "trade_updated",
        "trade_closed"
    }

    def validate_events(self, events):
        errors = []
        seen_created = set()
        seen_closed = set()

        for index, event in enumerate(events):
            missing_fields = [
                field for field in self.REQUIRED_FIELDS
                if field not in event
            ]

            if missing_fields:
                errors.append({
                    "index": index,
                    "reason": "missing_required_fields",
                    "missing_fields": missing_fields
                })
                continue

            trade_id = event.get("trade_id")
            event_type = event.get("event_type")

            if event_type not in self.VALID_EVENT_TYPES:
                errors.append({
                    "index": index,
                    "trade_id": trade_id,
                    "reason": "invalid_event_type",
                    "event_type": event_type
                })
                continue

            try:
                datetime.fromisoformat(event.get("timestamp"))
            except Exception:
                errors.append({
                    "index": index,
                    "trade_id": trade_id,
                    "reason": "invalid_timestamp"
                })
                continue

            if event_type == "trade_created":
                if trade_id in seen_created:
                    errors.append({
                        "index": index,
                        "trade_id": trade_id,
                        "reason": "duplicate_trade_created"
                    })
                seen_created.add(trade_id)

            if event_type in {"trade_updated", "trade_closed"}:
                if trade_id not in seen_created:
                    errors.append({
                        "index": index,
                        "trade_id": trade_id,
                        "reason": "event_before_trade_created"
                    })

            if event_type == "trade_closed":
                if trade_id in seen_closed:
                    errors.append({
                        "index": index,
                        "trade_id": trade_id,
                        "reason": "duplicate_trade_closed"
                    })
                seen_closed.add(trade_id)

        return {
            "valid": len(errors) == 0,
            "event_count": len(events),
            "error_count": len(errors),
            "errors": errors,
            "status": "EVENT_LEDGER_VALID" if len(errors) == 0 else "EVENT_LEDGER_INVALID"
        }
