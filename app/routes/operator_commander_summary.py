from datetime import datetime
from fastapi import APIRouter

from app.services.greyline_reliability_core_engine import GreyLineReliabilityCoreEngine
from app.services.reliability_governor_engine import ReliabilityGovernorEngine
from app.services.operator_notification_engine import OperatorNotificationEngine
from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine
from app.services.execution_authority_engine import ExecutionAuthorityEngine

router = APIRouter()


@router.get("/operator-commander-summary")
def operator_commander_summary():
    reliability = GreyLineReliabilityCoreEngine().evaluate()
    governor = ReliabilityGovernorEngine().evaluate()
    notifications = OperatorNotificationEngine().unread()
    decision = GreyLineMasterDecisionEngine().evaluate()
    authority = ExecutionAuthorityEngine().evaluate()

    top = decision.get("top_candidate") or {}
    decision_name = decision.get("decision")
    unread = notifications.get("unread_count") or 0

    status = "GREEN"
    action_required = False
    headline = "GreyLine operational."

    if reliability.get("status") != "RELIABILITY_CORE_HEALTHY":
        status = "YELLOW"
        headline = "Reliability degraded; execution authority restricted."
        action_required = True
    elif decision_name == "EXECUTE_SIGNAL_BLOCKED_READ_ONLY":
        status = "GREEN"
        headline = f"{top.get('symbol', '--')} {top.get('option_type', '--')} ready; live order placement disabled."
    elif unread > 0:
        status = "YELLOW"
        headline = f"{unread} unread operator notification(s)."
        action_required = True

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": "GreyLine",
        "operator_summary": {
            "status": status,
            "headline": headline,
            "action_required": action_required,
            "unread_notifications": unread,
            "operating_mode": authority.get("governor_mode"),
            "execution_allowed": authority.get("paper_execution_allowed"),
            "execution_authority": authority.get("execution_authority"),
            "paper_execution_allowed": authority.get("paper_execution_allowed"),
            "live_execution_allowed": authority.get("live_execution_allowed"),
            "reliability_score": reliability.get("health_score"),
            "master_decision": decision_name,
            "top_symbol": top.get("symbol"),
            "top_option_type": top.get("option_type"),
            "top_score": top.get("composite_score"),
        },
        "status": "OPERATOR_COMMANDER_SUMMARY_READY",
    }
