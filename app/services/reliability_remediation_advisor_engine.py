from datetime import datetime

from app.services.unified_reliability_core_engine import UnifiedReliabilityCoreEngine


class ReliabilityRemediationAdvisorEngine:
    """
    Read-only reliability remediation advisor.

    Converts reliability failures into operator-facing recovery actions.
    Does not restart services, refresh tokens, or place/cancel orders.
    """

    def evaluate(self, simulate_fault=None):
        reliability = UnifiedReliabilityCoreEngine().evaluate(simulate_fault=simulate_fault)
        checks = reliability.get("checks") or []

        actions = []
        for c in checks:
            if c.get("status") in ["YELLOW", "RED"]:
                actions.append(self._action_for(c))

        if not actions:
            posture = "NO_ACTION_REQUIRED"
        elif any(a.get("severity") == "CRITICAL" for a in actions):
            posture = "OPERATOR_ACTION_REQUIRED"
        else:
            posture = "MONITOR_OR_SCHEDULED_ACTION"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "RELIABILITY_REMEDIATION_ADVISOR",
            "overall_reliability": reliability.get("overall_reliability"),
            "reliability_score": reliability.get("reliability_score"),
            "posture": posture,
            "actions": actions,
            "simulate_fault": simulate_fault,
            "status": "RELIABILITY_REMEDIATION_ADVISOR_READY",
        }

    def _action_for(self, check):
        name = check.get("check")
        status = check.get("status")
        message = check.get("message")

        if name == "background_scheduler":
            return {
                "check": name,
                "severity": "CRITICAL" if status == "RED" else "WARNING",
                "problem": message,
                "recommended_action": "Restart or run the background scheduler status/start endpoint, then verify thread_alive is true.",
                "verification_endpoint": "/background-scheduler/status",
            }

        if name == "quote_heartbeat":
            return {
                "check": name,
                "severity": "CRITICAL" if status == "RED" else "WARNING",
                "problem": message,
                "recommended_action": "Restart fast quote heartbeat or run one heartbeat cycle, then verify quote heartbeat status is alive.",
                "verification_endpoint": "/fast-quote-heartbeat/status",
            }

        if name == "tradestation_token":
            return {
                "check": name,
                "severity": "CRITICAL" if status == "RED" else "WARNING",
                "problem": message,
                "recommended_action": "Refresh the TradeStation token and verify token status is ready for read-only.",
                "verification_endpoint": "/tradestation-token-status",
            }

        if name == "system_health":
            return {
                "check": name,
                "severity": "CRITICAL" if status == "RED" else "WARNING",
                "problem": message,
                "recommended_action": "Inspect /system-health-snapshot for repository, filesystem, or artifact issues.",
                "verification_endpoint": "/system-health-snapshot",
            }

        return {
            "check": name,
            "severity": "WARNING",
            "problem": message,
            "recommended_action": "Inspect unified reliability core details.",
            "verification_endpoint": "/unified-reliability-core",
        }
