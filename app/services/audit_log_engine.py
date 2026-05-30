from datetime import datetime


class AuditLogEngine:

    def create_log(self, action, status, details):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "status": status,
            "details": details
        }
