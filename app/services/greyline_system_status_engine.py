from datetime import datetime

from app.services.backend_control_center_engine import BackendControlCenterEngine
from app.services.system_health_dashboard_engine import SystemHealthDashboardEngine
from app.services.ledger_health_dashboard_engine import LedgerHealthDashboardEngine
from app.services.integrity_control_center_engine import IntegrityControlCenterEngine
from app.services.execution_authorization_gate_engine import ExecutionAuthorizationGateEngine


class GreyLineSystemStatusEngine:

    def get_system_status(self, requested_mode="paper"):

        control_center = BackendControlCenterEngine().get_control_center()
        system_health = SystemHealthDashboardEngine().status()
        ledger_health = LedgerHealthDashboardEngine().get_dashboard()
        integrity = IntegrityControlCenterEngine().evaluate()

        execution = ExecutionAuthorizationGateEngine().authorize(
            {
                "health_level": (
                    "GREEN"
                    if system_health.get("overall_health") == "HEALTHY"
                    else "RED"
                ),
                "integrity_pass": integrity.get("integrity_pass")
            },
            requested_mode
        )

        system_operational = all([
            control_center.get("system_status") == "OPERATIONAL",
            system_health.get("overall_health") == "HEALTHY",
            ledger_health.get("status") == "LEDGER_HEALTHY",
            execution.get("execution_authorized") is False or requested_mode == "paper"
        ])

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "mode": requested_mode,

            "control_center": control_center,
            "system_health": system_health,
            "ledger_health": ledger_health,
            "integrity": integrity,
            "execution": execution,

            "system_operational": system_operational,

            "status": (
                "GREYLINE_SYSTEM_OPERATIONAL"
                if system_operational
                else "GREYLINE_SYSTEM_DEGRADED"
            )
        }
