from datetime import datetime


class ExecutionGovernor:

    def evaluate_execution_permission(self, signal):
        signal = str(signal).upper().strip()

        execution_enabled = False
        live_trading_enabled = False

        blocked = (
            signal == "EXECUTE"
            and (
                execution_enabled is False
                or live_trading_enabled is False
            )
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "signal": signal,
            "execution_signal_allowed": signal in ["EXECUTE", "WATCH", "REJECT"],
            "order_placement_allowed": False,
            "execution_enabled": execution_enabled,
            "live_trading_enabled": live_trading_enabled,
            "blocked": blocked,
            "status": "EXECUTION_BLOCKED" if blocked else "NO_EXECUTION_REQUESTED"
        }
