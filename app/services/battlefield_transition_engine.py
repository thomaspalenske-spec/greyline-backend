from datetime import datetime


class BattlefieldTransitionEngine:

    def evaluate(self, history):

        if len(history) < 2:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "transition_state": "INSUFFICIENT_HISTORY",
                "status": "BATTLEFIELD_TRANSITION_READY",
            }

        previous = history[-2].get("battlefield_health")
        current = history[-1].get("battlefield_health")

        transition = f"{previous}_TO_{current}"

        improving = transition in [
            "RED_TO_YELLOW",
            "YELLOW_TO_GREEN",
        ]

        deteriorating = transition in [
            "GREEN_TO_YELLOW",
            "YELLOW_TO_RED",
        ]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "previous_state": previous,
            "current_state": current,
            "transition_state": transition,
            "improving": improving,
            "deteriorating": deteriorating,
            "status": "BATTLEFIELD_TRANSITION_READY",
        }
