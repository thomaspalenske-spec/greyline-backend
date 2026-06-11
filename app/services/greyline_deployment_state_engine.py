from datetime import datetime


class GreyLineDeploymentStateEngine:

    def __init__(self):

        self.state = "SIMULATION"

    def transition(self, new_state):

        valid_states = [
            "SIMULATION",
            "PAPER",
            "ARMED",
            "LIVE_ENABLED",
            "LIVE_EXECUTION"
        ]

        if new_state not in valid_states:
            return {
                "status": "INVALID_STATE",
                "state": self.state
            }

        # HARD SAFETY RULES
        if new_state == "LIVE_EXECUTION":
            if self.state != "LIVE_ENABLED":
                return {
                    "status": "BLOCKED_INVALID_TRANSITION",
                    "from": self.state,
                    "to": new_state
                }

        self.state = new_state

        return {
            "status": "STATE_UPDATED",
            "state": self.state,
            "timestamp": datetime.utcnow().isoformat()
        }

    def status(self):

        return {
            "state": self.state,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "DEPLOYMENT_CONTROLLER_ACTIVE"
        }
