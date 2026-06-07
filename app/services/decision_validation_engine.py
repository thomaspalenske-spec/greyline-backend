from datetime import datetime

from app.services.decision_replay_engine import DecisionReplayEngine


class DecisionValidationEngine:

    def validate(self, limit=50):
        replay = DecisionReplayEngine().replay_recent_decisions(limit=limit)
        decisions = replay.get("replayed_decisions", [])

        validations = []

        validated_count = 0
        pending_count = 0
        insufficient_data_count = 0

        for item in decisions:
            symbol = item.get("symbol")
            decision = item.get("decision")
            replay_state = item.get("replay_state")

            validation_status = "PENDING_VALIDATION"
            validation_result = "INSUFFICIENT_FORWARD_DATA"
            validation_reason = "Forward price/outcome data is not yet attached to this decision event"

            if not symbol:
                validation_status = "INSUFFICIENT_DATA"
                validation_result = "NO_SYMBOL_ATTACHED"
                validation_reason = "Decision event has no top candidate symbol"
                insufficient_data_count += 1
            else:
                pending_count += 1

            validations.append({
                "timestamp": item.get("original_timestamp"),
                "decision": decision,
                "symbol": symbol,
                "replay_state": replay_state,
                "validation_status": validation_status,
                "validation_result": validation_result,
                "validation_reason": validation_reason,
                "execution_enabled": False,
                "order_placement_allowed": False,
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_VALIDATION",
            "events_analyzed": len(validations),
            "validated_count": validated_count,
            "pending_count": pending_count,
            "insufficient_data_count": insufficient_data_count,
            "validations": validations,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_VALIDATION_READY",
        }
