from datetime import datetime

from app.services.live_broker_health_engine import LiveBrokerHealthEngine
from app.services.risk_engine import RiskEngine
from app.services.opportunity_summary_engine import OpportunitySummaryEngine
from app.services.execution_governor import ExecutionGovernor
from app.services.master_decision_event_log import MasterDecisionEventLog


class GreyLineMasterDecisionEngine:

    def evaluate(self):
        broker_health = LiveBrokerHealthEngine().evaluate()
        risk_state = RiskEngine().evaluate_risk_state()
        opportunity_summary = OpportunitySummaryEngine().get_summary()

        opportunities = opportunity_summary.get("opportunities", [])
        execute_candidates = [
            item for item in opportunities
            if item.get("result") == "EXECUTE"
        ]

        top_candidate = None
        if execute_candidates:
            top_candidate = sorted(
                execute_candidates,
                key=lambda item: item.get("composite_score", 0),
                reverse=True
            )[0]

        broker_ready = broker_health.get("health_score") == 100
        risk_allows = risk_state == "NORMAL"
        candidate_available = top_candidate is not None

        decision = "NO_ACTION"
        reason = "No EXECUTE candidate available"

        if candidate_available and broker_ready and risk_allows:
            decision = "EXECUTE_SIGNAL_BLOCKED_READ_ONLY"
            reason = "Best candidate meets decision criteria, but order placement is disabled"
        elif candidate_available and not broker_ready:
            decision = "NO_ACTION"
            reason = "Broker health is not ready"
        elif candidate_available and not risk_allows:
            decision = "NO_ACTION"
            reason = f"Risk state does not allow execution: {risk_state}"

        governor = ExecutionGovernor().evaluate_execution_permission(
            top_candidate.get("result") if top_candidate else "NO_ACTION"
        )

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "MASTER_DECISION_READ_ONLY",
            "broker_ready": broker_ready,
            "broker_health": broker_health,
            "risk_state": risk_state,
            "symbols_scored": opportunity_summary.get("symbols_scored", 0),
            "top_candidate": top_candidate,
            "decision": decision,
            "decision_reason": reason,
            "governor": governor,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "GREYLINE_MASTER_DECISION_READY"
        }

        log_result = MasterDecisionEventLog().record_decision(result)
        result["decision_event_logged"] = log_result.get("event_logged")
        result["decision_event_log_status"] = log_result.get("status")

        return result
