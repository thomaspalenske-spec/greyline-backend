from datetime import datetime
from fastapi import APIRouter

from app.services.reliability_governor_engine import ReliabilityGovernorEngine
from app.services.unified_reliability_core_engine import UnifiedReliabilityCoreEngine
from app.services.operator_notification_engine import OperatorNotificationEngine
from app.services.operator_event_bus_engine import OperatorEventBusEngine
from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine

router = APIRouter()


@router.get("/operator-cockpit-status")
def operator_cockpit_status(include_master_decision: bool = False):
    reliability = UnifiedReliabilityCoreEngine().evaluate()
    governor = ReliabilityGovernorEngine().evaluate()
    notifications = OperatorNotificationEngine().unread()
    events = OperatorEventBusEngine().recent(limit=10)

    master_decision = None
    if include_master_decision:
        master_decision = GreyLineMasterDecisionEngine().evaluate()

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": "GreyLine",
        "overall_reliability": reliability.get("overall_reliability"),
        "reliability_score": reliability.get("reliability_score"),
        "reliability_summary": reliability.get("summary"),
        "operating_mode": governor.get("operating_mode"),
        "execution_allowed": governor.get("execution_allowed"),
        "new_entries_allowed": governor.get("new_entries_allowed"),
        "autonomous_allowed": governor.get("autonomous_allowed"),
        "unread_notifications": notifications.get("unread_count"),
        "latest_events": events.get("events"),
        "master_decision": master_decision,
        "status": "OPERATOR_COCKPIT_STATUS_READY",
    }
