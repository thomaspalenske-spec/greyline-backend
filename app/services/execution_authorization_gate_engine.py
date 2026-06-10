from datetime import datetime


class ExecutionAuthorizationGateEngine:

    def authorize(
        self,
        governance_dashboard,
        requested_mode="paper"
    ):
        health_level = governance_dashboard.get("health_level")
        integrity_pass = governance_dashboard.get("integrity_pass") is True
        execution_requested = requested_mode in ["paper", "live"]

        reasons = []

        if not execution_requested:
            reasons.append("INVALID_REQUESTED_MODE")

        if health_level != "GREEN":
            reasons.append("GOVERNANCE_NOT_GREEN")

        if integrity_pass is not True:
            reasons.append("INTEGRITY_NOT_PASSED")

        execution_authorized = (
            execution_requested
            and health_level == "GREEN"
            and integrity_pass is True
            and requested_mode == "paper"
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "requested_mode": requested_mode,
            "health_level": health_level,
            "integrity_pass": integrity_pass,
            "execution_authorized": execution_authorized,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "authorization_reasons": reasons,
            "status": "EXECUTION_AUTHORIZED_PAPER" if execution_authorized else "EXECUTION_DENIED"
        }
