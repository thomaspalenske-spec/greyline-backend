from datetime import datetime


class BrokerKillSwitchEngine:

    def evaluate_kill_switch(
        self,
        emergency_stop_active,
        broker_connected,
        autonomous_execution_enabled
    ):

        trading_allowed = (
            not emergency_stop_active
            and broker_connected
            and not autonomous_execution_enabled
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "emergency_stop_active": emergency_stop_active,
            "broker_connected": broker_connected,
            "autonomous_execution_enabled": autonomous_execution_enabled,
            "trading_allowed": trading_allowed,
            "kill_switch_status": "ACTIVE" if emergency_stop_active else "STANDBY"
        }
