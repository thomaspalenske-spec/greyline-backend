from datetime import datetime

from app.services.integrity_control_center_engine import IntegrityControlCenterEngine


class BackendControlCenterEngine:

    def get_control_center(self):
        integrity = IntegrityControlCenterEngine().evaluate()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "backend_version": "0.21.0",
            "mode": "LOCAL_DEVELOPMENT",
            "system_status": "OPERATIONAL",
            "backend_ready": True,
            "capability_registry": "ACTIVE",
            "ucf_registry": "ACTIVE",
            "milestone_registry": "ACTIVE",
            "control_center": "ONLINE",
            "integrity_pass": integrity.get("integrity_pass"),
            "execution_allowed": False,
            "order_placement_allowed": False,
            "integrity_status": integrity.get("status"),
            "integrity_control_center": integrity,
            "status": "GREYLINE_CONTROL_CENTER_READY" if integrity.get("integrity_pass") else "GREYLINE_CONTROL_CENTER_BLOCKED"
        }
