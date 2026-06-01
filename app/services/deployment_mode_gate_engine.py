from datetime import datetime


class DeploymentModeGateEngine:

    ALLOWED_MODES = [
        "LOCAL_DEVELOPMENT",
        "PAPER_TRADING_PREP",
        "PAPER_TRADING",
        "LIVE_PREP",
        "LIVE_TRADING"
    ]

    BLOCKED_MODES = [
        "LIVE_TRADING"
    ]

    def evaluate_mode(self, requested_mode):

        allowed_mode = requested_mode in self.ALLOWED_MODES
        blocked_mode = requested_mode in self.BLOCKED_MODES

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "requested_mode": requested_mode,
            "allowed_modes": self.ALLOWED_MODES,
            "blocked_modes": self.BLOCKED_MODES,
            "mode_exists": allowed_mode,
            "transition_allowed": allowed_mode and not blocked_mode,
            "status": "MODE_ALLOWED" if allowed_mode and not blocked_mode else "MODE_BLOCKED",
        }
