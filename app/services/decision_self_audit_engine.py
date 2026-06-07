from datetime import datetime

from app.services.decision_performance_attribution_engine import DecisionPerformanceAttributionEngine
from app.services.decision_outcome_tracking_engine import DecisionOutcomeTrackingEngine


class DecisionSelfAuditEngine:

    def analyze(self, limit=50):
        performance = DecisionPerformanceAttributionEngine().analyze(limit=limit)
        outcomes = DecisionOutcomeTrackingEngine().analyze(limit=limit)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_SELF_AUDIT",
            "events_analyzed": max(
                performance.get("events_analyzed", 0),
                outcomes.get("events_analyzed", 0),
            ),
            "decision_performance": performance,
            "decision_outcomes": outcomes,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_SELF_AUDIT_READY",
        }
