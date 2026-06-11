from datetime import datetime


class GreyLineSafetyGateEngine:

    def __init__(self):
        self.live_enabled = False
        self.kill_switch = False

    def enable_live_trading(self):
        if self.kill_switch:
            return {
                "status": "BLOCKED_BY_KILL_SWITCH",
                "live_enabled": False
            }

        self.live_enabled = True
        return {
            "status": "LIVE_TRADING_ENABLED",
            "live_enabled": True,
            "timestamp": datetime.utcnow().isoformat()
        }

    def disable_live_trading(self):
        self.live_enabled = False
        return {
            "status": "LIVE_TRADING_DISABLED",
            "live_enabled": False,
            "timestamp": datetime.utcnow().isoformat()
        }

    def activate_kill_switch(self):
        self.kill_switch = True
        self.live_enabled = False
        return {
            "status": "KILL_SWITCH_ACTIVATED",
            "live_enabled": False,
            "kill_switch": True,
            "timestamp": datetime.utcnow().isoformat()
        }

    def can_execute_live(self):
        return self.live_enabled and not self.kill_switch

    def status(self):
        return {
            "live_enabled": self.live_enabled,
            "kill_switch": self.kill_switch,
            "can_execute_live": self.can_execute_live(),
            "status": "SAFETY_GATE_ACTIVE"
        }
