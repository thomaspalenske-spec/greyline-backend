from datetime import datetime


class BrokerSafetySummaryEngine:

    def summarize_safety(
        self,
        safe_for_broker_prep,
        authority_approved,
        execution_blocked,
        kill_switch_status,
        trading_allowed
    ):

        broker_safety_status = "SAFE_FOR_PREP"

        if not safe_for_broker_prep:
            broker_safety_status = "NOT_READY"

        if not authority_approved:
            broker_safety_status = "AUTHORITY_BLOCKED"

        if execution_blocked:
            broker_safety_status = "EXECUTION_BLOCKED"

        if kill_switch_status == "ACTIVE":
            broker_safety_status = "KILL_SWITCH_ACTIVE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "safe_for_broker_prep": safe_for_broker_prep,
            "authority_approved": authority_approved,
            "execution_blocked": execution_blocked,
            "kill_switch_status": kill_switch_status,
            "trading_allowed": trading_allowed,
            "broker_safety_status": broker_safety_status
        }
