from datetime import datetime


class RuntimeSafetySummaryEngine:

    def summarize_runtime_safety(
        self,
        broker_connected,
        autonomous_execution_enabled,
        authority_level,
        kill_switch_status,
        credential_safety_approved
    ):

        runtime_safe = (
            not broker_connected
            and not autonomous_execution_enabled
            and authority_level == "OBSERVE_RECOMMEND_ONLY"
            and kill_switch_status == "STANDBY"
            and credential_safety_approved
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker_connected": broker_connected,
            "autonomous_execution_enabled": autonomous_execution_enabled,
            "authority_level": authority_level,
            "kill_switch_status": kill_switch_status,
            "credential_safety_approved": credential_safety_approved,
            "runtime_safe": runtime_safe,
            "status": "RUNTIME_SAFE" if runtime_safe else "RUNTIME_UNSAFE"
        }
