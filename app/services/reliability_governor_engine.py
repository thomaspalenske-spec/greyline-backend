from datetime import datetime

from app.services.reliability_remediation_advisor_engine import ReliabilityRemediationAdvisorEngine


class ReliabilityGovernorEngine:
    """
    Reliability authority gate.

    Converts reliability status into operational authority.
    Does not place trades, cancel orders, or restart services.
    """

    def evaluate(self, simulate_fault=None):
        advisor = ReliabilityRemediationAdvisorEngine().evaluate(simulate_fault=simulate_fault)

        score = int(advisor.get("reliability_score") or 0)
        reliability = advisor.get("overall_reliability")
        posture = advisor.get("posture")
        actions = advisor.get("actions") or []

        critical_actions = [a for a in actions if a.get("severity") == "CRITICAL"]

        if reliability == "GREEN" and score >= 95:
            mode = "FULL_OPERATIONAL"
            execution_allowed = True
            new_entries_allowed = True
            autonomous_allowed = True
            reason = "Reliability green and score at or above 95."

        elif reliability == "YELLOW" and score >= 85:
            mode = "RECOMMEND_ONLY"
            execution_allowed = False
            new_entries_allowed = False
            autonomous_allowed = False
            reason = "Reliability degraded. Recommendations allowed; execution blocked."

        elif critical_actions or reliability == "RED":
            mode = "SAFE_MODE"
            execution_allowed = False
            new_entries_allowed = False
            autonomous_allowed = False
            reason = "Critical reliability issue detected. Execution blocked."

        else:
            mode = "OBSERVE_ONLY"
            execution_allowed = False
            new_entries_allowed = False
            autonomous_allowed = False
            reason = "Reliability below operational threshold."

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "RELIABILITY_GOVERNOR",
            "operating_mode": mode,
            "execution_allowed": execution_allowed,
            "new_entries_allowed": new_entries_allowed,
            "autonomous_allowed": autonomous_allowed,
            "reason": reason,
            "overall_reliability": reliability,
            "reliability_score": score,
            "posture": posture,
            "critical_action_count": len(critical_actions),
            "actions": actions,
            "simulate_fault": simulate_fault,
            "status": "RELIABILITY_GOVERNOR_READY",
        }
