from datetime import datetime
from fastapi import APIRouter

from app.services.greyline_reliability_core_engine import GreyLineReliabilityCoreEngine
from app.services.reliability_governor_engine import ReliabilityGovernorEngine
from app.services.operator_notification_engine import OperatorNotificationEngine
from app.services.master_decision_history_engine import MasterDecisionHistoryEngine
from app.services.execution_authority_engine import ExecutionAuthorityEngine

router = APIRouter()


def _recorded_master_decision():
    """The decision GreyLineMasterDecisionEngine last recorded.

    This is a display route: it reports the engine's decision, it does not cause one.
    Calling GreyLineMasterDecisionEngine().evaluate() here re-ran a full ~12s scoring
    cycle on every dashboard poll AND appended a decision event each time (evaluate()
    ends in MasterDecisionEventLog().record_decision()), so the operator dashboard was
    writing thousands of spurious trading decisions into the audit log and jamming its
    own 15s refresh. Read the recorded decision instead.
    """
    try:
        events = MasterDecisionHistoryEngine().get_history(limit=1).get("events") or []
        return events[-1] if events else {}
    except Exception:
        return {}


@router.get("/operator-commander-summary")
def operator_commander_summary():
    reliability = GreyLineReliabilityCoreEngine().evaluate()
    governor = ReliabilityGovernorEngine().evaluate()
    notifications = OperatorNotificationEngine().unread()
    decision = _recorded_master_decision()
    authority = ExecutionAuthorityEngine().evaluate(decision=decision)

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
        symbol = top.get("symbol", "--")
        option_type = top.get("option_type", "--")
        if authority.get("paper_execution_allowed") is True and authority.get("live_execution_allowed") is not True:
            headline = f"Paper Trader active: {symbol} {option_type} qualified; live orders remain locked."
        else:
            headline = f"{symbol} {option_type} qualified; execution authority restricted."
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
            "execution_authority_reason": authority.get("reason"),
            "paper_execution_allowed": authority.get("paper_execution_allowed"),
            "live_execution_allowed": authority.get("live_execution_allowed"),
            "paper_execution_enabled": authority.get("paper_execution_enabled"),
            "live_execution_enabled": authority.get("live_execution_enabled"),
            "signal_decision": authority.get("signal_decision"),
            "reliability_score": reliability.get("health_score"),
            "master_decision": decision_name,
            "top_symbol": top.get("symbol"),
            "top_option_type": top.get("option_type"),
            "top_score": top.get("composite_score"),
        },
        "status": "OPERATOR_COMMANDER_SUMMARY_READY",
    }
