from datetime import datetime

from app.routes.greyline_system_status_route import endpoint as system_status


class GreyLineSystemControlLoopEngine:

    def run_cycle(self):

        status = system_status(requested_mode="paper")

        operational = status.get("system_operational", False)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system_operational": operational,
            "system_status": status.get("status"),
            "ledger_status": status.get("ledger_health", {}).get("status"),
            "mode": status.get("mode"),
            "execution_enabled": status.get("execution", {}).get("execution_authorized"),
            "status": (
                "CONTROL_LOOP_OK"
                if operational
                else "CONTROL_LOOP_DEGRADED"
            )
        }
