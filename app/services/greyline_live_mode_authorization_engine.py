from datetime import datetime


class GreyLineLiveModeAuthorizationEngine:

    def __init__(self, safety_gate):

        self.safety_gate = safety_gate
        self.armed = False
        self.authorization_token = None

    def arm_live_mode(self):

        self.armed = True
        self.authorization_token = f"ARM-{datetime.utcnow().timestamp()}"

        return {
            "status": "LIVE_MODE_ARMED",
            "armed": True,
            "authorization_token": self.authorization_token,
            "timestamp": datetime.utcnow().isoformat()
        }

    def confirm_live_enable(self, token):

        if not self.armed:
            return {
                "status": "LIVE_MODE_NOT_ARMED",
                "live_enabled": False
            }

        if token != self.authorization_token:
            return {
                "status": "INVALID_AUTHORIZATION_TOKEN",
                "live_enabled": False
            }

        if self.safety_gate.kill_switch:
            return {
                "status": "BLOCKED_KILL_SWITCH_ACTIVE",
                "live_enabled": False
            }

        self.safety_gate.live_enabled = True

        return {
            "status": "LIVE_MODE_ENABLED",
            "live_enabled": True,
            "timestamp": datetime.utcnow().isoformat()
        }

    def disable_live_mode(self):

        self.safety_gate.live_enabled = False
        self.armed = False
        self.authorization_token = None

        return {
            "status": "LIVE_MODE_DISABLED",
            "live_enabled": False,
            "timestamp": datetime.utcnow().isoformat()
        }

    def status(self):

        return {
            "armed": self.armed,
            "live_enabled": self.safety_gate.live_enabled,
            "kill_switch": self.safety_gate.kill_switch,
            "status": "LIVE_AUTHORIZATION_LAYER_ACTIVE"
        }
