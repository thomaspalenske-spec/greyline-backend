from datetime import datetime


class OpportunityEscalationEngine:

    def evaluate(self, queue):

        candidate = queue.get("top_candidate")

        if not candidate:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "escalation_state": "NONE",
                "status": "OPPORTUNITY_ESCALATION_READY",
            }

        distance = candidate.get(
            "score_distance_to_execute",
            999
        )

        if distance <= 1:
            state = "IMMINENT"

        elif distance <= 3:
            state = "APPROACHING"

        elif distance <= 5:
            state = "WATCH"

        else:
            state = "NONE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "escalation_state": state,
            "symbol": candidate.get("symbol"),
            "distance_to_execute": distance,
            "status": "OPPORTUNITY_ESCALATION_READY",
        }
