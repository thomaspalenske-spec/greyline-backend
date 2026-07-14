from datetime import datetime

from app.services.decision_self_audit_engine import (
    DecisionSelfAuditEngine,
)
from app.services.decision_outcome_scoring_engine import (
    DecisionOutcomeScoringEngine,
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

        # Real decision quality: weighted directional accuracy of scored forward
        # outcomes (favorable = full credit, neutral = half, unfavorable = zero).
        # None when nothing has been scored yet — never a fabricated perfect score.
        scoring = DecisionOutcomeScoringEngine().score(limit=limit)
        favorable = scoring.get("favorable_count", 0)
        unfavorable = scoring.get("unfavorable_count", 0)
        neutral = scoring.get("neutral_count", 0)
        scored = favorable + unfavorable + neutral

        if scored > 0:
            quality_score = round(100 * (favorable + 0.5 * neutral) / scored, 2)
        else:
            quality_score = None

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_METRICS_DASHBOARD",
            "events_analyzed": events,
            "execute_signals": execute_signals,
            "no_actions": no_actions,
            "pending_validation": pending_validation,
            "decision_quality_score": quality_score,
            "decision_quality_basis": {
                "favorable": favorable,
                "neutral": neutral,
                "unfavorable": unfavorable,
                "scored": scored,
                "formula": "100 * (favorable + 0.5*neutral) / scored",
            },
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_METRICS_READY"
        }
