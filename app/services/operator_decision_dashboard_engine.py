from datetime import datetime

from app.services.decision_metrics_dashboard_engine import DecisionMetricsDashboardEngine
from app.services.decision_self_audit_engine import DecisionSelfAuditEngine


class OperatorDecisionDashboardEngine:

    def summarize(self, limit=50):
        metrics = DecisionMetricsDashboardEngine().summarize(limit=limit)
        audit = DecisionSelfAuditEngine().analyze(limit=limit)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "OPERATOR_DECISION_DASHBOARD",
            "metrics": metrics,
            "self_audit": audit,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "OPERATOR_DECISION_DASHBOARD_READY",
        }
