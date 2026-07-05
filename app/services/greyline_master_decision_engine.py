from datetime import datetime
from app.services.operator_event_bus_engine import OperatorEventBusEngine

from app.services.live_broker_health_engine import LiveBrokerHealthEngine
from app.services.risk_engine import RiskEngine
from app.services.opportunity_summary_engine import OpportunitySummaryEngine
from app.services.execution_governor import ExecutionGovernor
from app.services.master_decision_event_log import MasterDecisionEventLog
from app.services.opportunity_symmetry_engine import OpportunitySymmetryEngine
from app.services.institutional_flow_engine import InstitutionalFlowEngine
from app.services.bear_market_opportunity_engine import BearMarketOpportunityEngine
from app.services.reliability_governor_engine import ReliabilityGovernorEngine


class GreyLineMasterDecisionEngine:

    def evaluate(self):
        broker_health = LiveBrokerHealthEngine().evaluate()
        risk_state = RiskEngine().evaluate_risk_state()
        opportunity_summary = OpportunitySummaryEngine().get_summary(limit=50)

        opportunities = opportunity_summary.get("opportunities", [])

        opportunity_symmetry = OpportunitySymmetryEngine().evaluate(opportunities)
        bear_market_opportunity = BearMarketOpportunityEngine().evaluate(opportunities)

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
        elif opportunities:
            top_candidate = sorted(
                opportunities,
                key=lambda item: item.get("composite_score", 0),
                reverse=True
            )[0]

        broker_ready = broker_health.get("health_score") == 100
        risk_allows = risk_state == "NORMAL"
        candidate_available = top_candidate is not None
        execute_candidate_available = top_candidate is not None and top_candidate.get("result") == "EXECUTE"

        decision = "NO_ACTION"
        reason = "No EXECUTE candidate available"

        if execute_candidate_available and broker_ready and risk_allows:
            decision = "EXECUTE_SIGNAL_BLOCKED_READ_ONLY"
            reason = "Best EXECUTE candidate meets decision criteria, but order placement is disabled"
        elif execute_candidate_available and not broker_ready:
            decision = "NO_ACTION"
            reason = "Broker health is not ready"
        elif execute_candidate_available and not risk_allows:
            decision = "NO_ACTION"
            reason = f"Risk state does not allow execution: {risk_state}"
        elif candidate_available:
            decision = "NO_ACTION"
            reason = f"Best candidate is {top_candidate.get('result')}, not EXECUTE"

        governor = ExecutionGovernor().evaluate_execution_permission(
            top_candidate.get("result") if top_candidate else "NO_ACTION"
        )

        reliability_governor = ReliabilityGovernorEngine().evaluate()

        institutional_flow = InstitutionalFlowEngine().evaluate({
            "symbols_scored": opportunity_summary.get("symbols_scored", 0),
            "top_candidate": top_candidate,
            "risk_state": risk_state,
            "symmetry": opportunity_symmetry,
        })

        top = top_candidate or {}

        decision_event_category = "DECISION"
        decision_event_severity = "INFO"
        decision_ack_required = False

        if decision == "EXECUTE_SIGNAL_BLOCKED_READ_ONLY":
            decision_event_category = "EXECUTION_BLOCKED"
            decision_event_severity = "WARNING"
            decision_ack_required = True

        operator_event_result = OperatorEventBusEngine().publish(
            source="GreyLineMasterDecisionEngine",
            category=decision_event_category,
            severity=decision_event_severity,
            title=f"Master Decision: {decision}",
            message=f"{top.get('symbol', '--')} {top.get('option_type', '--')} decision: {decision}.",
            symbol=top.get("symbol"),
            trade_id=None,
            ack_required=decision_ack_required,
            payload={
                "decision": decision,
                "decision_reason": reason,
                "top_candidate": top,
                "reliability_governor": reliability_governor,
            },
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
            "candidate_available": candidate_available,
            "execute_candidate_available": execute_candidate_available,
            "opportunity_symmetry": opportunity_symmetry,
            "bear_market_opportunity": bear_market_opportunity,
            "institutional_flow": institutional_flow,
            "decision": decision,
            "decision_reason": reason,
            "governor": governor,
            "reliability_governor": reliability_governor,
            "reliability_operating_mode": reliability_governor.get("operating_mode"),
            "reliability_execution_allowed": reliability_governor.get("execution_allowed"),
            "reliability_new_entries_allowed": reliability_governor.get("new_entries_allowed"),
            "reliability_autonomous_allowed": reliability_governor.get("autonomous_allowed"),
            "reliability_score": reliability_governor.get("reliability_score"),
            "execution_enabled": False,
            "order_placement_allowed": False,
            "operator_event_result": operator_event_result,
            "operator_event_published": operator_event_result.get("event_published"),
            "operator_event_deduped": operator_event_result.get("deduped", False),
            "operator_event_status": operator_event_result.get("status"),
            "status": "GREYLINE_MASTER_DECISION_READY"
        }

        log_result = MasterDecisionEventLog().record_decision(result)
        result["decision_event_logged"] = log_result.get("event_logged")
        result["decision_event_log_status"] = log_result.get("status")

        return result
