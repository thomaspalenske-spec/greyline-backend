class PositionLifecycleValidatorEngine:

    VALID_EVENT_TYPES = {
        "trade_created",
        "trade_updated",
        "trade_closed"
    }

    def validate_lifecycle(self, events):
        errors = []
        created_trades = set()
        closed_trades = set()

        for index, event in enumerate(events):
            trade_id = event.get("trade_id")
            event_type = event.get("event_type")

            if not trade_id:
                errors.append({
                    "index": index,
                    "reason": "missing_trade_id"
                })
                continue

            if event_type not in self.VALID_EVENT_TYPES:
                errors.append({
                    "index": index,
                    "trade_id": trade_id,
                    "reason": "invalid_event_type"
                })
                continue

            if event_type == "trade_created":
                if trade_id in created_trades:
                    errors.append({
                        "index": index,
                        "trade_id": trade_id,
                        "reason": "duplicate_trade_created"
                    })
                if trade_id in closed_trades:
                    errors.append({
                        "index": index,
                        "trade_id": trade_id,
                        "reason": "trade_reopened_after_close"
                    })
                created_trades.add(trade_id)

            if event_type == "trade_updated":
                if trade_id not in created_trades:
                    errors.append({
                        "index": index,
                        "trade_id": trade_id,
                        "reason": "update_before_create"
                    })
                if trade_id in closed_trades:
                    errors.append({
                        "index": index,
                        "trade_id": trade_id,
                        "reason": "update_after_close"
                    })

            if event_type == "trade_closed":
                if trade_id not in created_trades:
                    errors.append({
                        "index": index,
                        "trade_id": trade_id,
                        "reason": "close_before_create"
                    })
                if trade_id in closed_trades:
                    errors.append({
                        "index": index,
                        "trade_id": trade_id,
                        "reason": "duplicate_trade_closed"
                    })
                closed_trades.add(trade_id)

        return {
            "valid": len(errors) == 0,
            "event_count": len(events),
            "error_count": len(errors),
            "errors": errors,
            "status": "POSITION_LIFECYCLE_VALID" if len(errors) == 0 else "POSITION_LIFECYCLE_INVALID"
        }
