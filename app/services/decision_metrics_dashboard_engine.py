from datetime import datetime

from app.services.decision_self_audit_engine import (
    DecisionSelfAuditEngine,
)


class DecisionMetricsDashboardEngine:

    def summarize(self, limit=50):

        audit = DecisionSelfAuditEngine().analyze(limit=limit)

        performance = audit.get("decision_performance", {})
        outcomes = audit.get("decision_outcomes", {})

        events = performance.get("events_analyzed", 0)

        execute_signals = performance.get(
            "execute_signal_count", 0
        )

        no_actions = performance.get(
            "no_action_count", 0
        )

        pending_validation = outcomes.get(
            "execute_signal_pending_validation", 0
        )

        quality_score = 100

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_METRICS_DASHBOARD",
            "events_analyzed": events,
            "execute_signals": execute_signals,
            "no_actions": no_actions,
            "pending_validation": pending_validation,
            "decision_quality_score": quality_score,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_METRICS_READY"
        }
