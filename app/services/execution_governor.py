from datetime import datetime
from os import getenv


class ExecutionGovernor:

    def evaluate_execution_permission(self, signal):
        signal = str(signal).upper().strip()

        # Fail-safe default: an unset flag means execution is BLOCKED, not armed.
        # Arming paper execution requires an explicit GREYLINE_PAPER_EXECUTION_ENABLED=true.
        paper_execution_enabled = getenv("GREYLINE_PAPER_EXECUTION_ENABLED", "false").lower() == "true"
        live_trading_enabled = getenv("GREYLINE_LIVE_TRADING_ENABLED", "false").lower() == "true"
        live_order_placement_allowed = getenv("GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED", "false").lower() == "true"

        execution_enabled = paper_execution_enabled or live_trading_enabled

        order_placement_allowed = (
            signal == "EXECUTE"
            and paper_execution_enabled is True
        )

        live_order_placement_allowed = (
            signal == "EXECUTE"
            and live_trading_enabled is True
            and live_order_placement_allowed is True
        )

        blocked = (
            signal == "EXECUTE"
            and execution_enabled is False
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "signal": signal,
            "execution_signal_allowed": signal in ["EXECUTE", "WATCH", "REJECT"],
            "execution_mode": "PAPER_ONLY" if paper_execution_enabled else "READ_ONLY",
            "order_placement_allowed": order_placement_allowed,
            "execution_enabled": execution_enabled,
            "paper_execution_enabled": paper_execution_enabled,
            "live_trading_enabled": live_trading_enabled,
            "live_order_placement_allowed": live_order_placement_allowed,
            "blocked": blocked,
            "status": "EXECUTION_ALLOWED_PAPER_ONLY" if order_placement_allowed else ("EXECUTION_BLOCKED" if blocked else "NO_EXECUTION_REQUESTED")
        }
