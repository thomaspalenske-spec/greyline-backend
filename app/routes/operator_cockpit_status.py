from datetime import datetime
from fastapi import APIRouter

from app.services.reliability_governor_engine import ReliabilityGovernorEngine
from app.services.unified_reliability_core_engine import UnifiedReliabilityCoreEngine
from app.services.operator_notification_engine import OperatorNotificationEngine
from app.services.operator_event_bus_engine import OperatorEventBusEngine
from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine
from app.services.fast_quote_heartbeat_service import FastQuoteHeartbeatService
from app.services.tradestation_token_status_engine import TradeStationTokenStatusEngine

router = APIRouter()


def _mission_readiness_score(reliability, governor, quote_heartbeat, token_status):
    score = 100
    reasons = []

    if reliability.get("overall_reliability") != "GREEN":
        score -= 25
        reasons.append("Reliability not GREEN.")

    if not governor.get("execution_allowed"):
        score -= 25
        reasons.append("Execution not allowed.")

    if not governor.get("new_entries_allowed"):
        score -= 15
        reasons.append("New entries not allowed.")

    if not quote_heartbeat.get("enabled") or not quote_heartbeat.get("thread_alive"):
        score -= 25
        reasons.append("Quote heartbeat offline.")
    else:
        quote_health = ((quote_heartbeat.get("state") or {}).get("market_data_health") or "UNKNOWN")
        if quote_health == "DEGRADED":
            score -= 10
            reasons.append("Quote feed degraded.")
        elif quote_health in ("STALE_DATA", "UNKNOWN"):
            score -= 25
            reasons.append("Quote feed stale or unknown.")

    token_ok = str(token_status.get("status") or "").upper()
    if "READY" not in token_ok and "VALID" not in token_ok:
        score -= 20
        reasons.append("TradeStation token not ready.")

    score = max(0, min(100, score))

    if score >= 95:
        status = "GO"
    elif score >= 80:
        status = "CAUTION"
    else:
        status = "NO_GO"

    return {
        "score": score,
        "status": status,
        "reasons": reasons or ["All primary readiness checks passed."],
    }



@router.get("/operator-cockpit-status")
def operator_cockpit_status(include_master_decision: bool = False):
    reliability = UnifiedReliabilityCoreEngine().evaluate()
    governor = ReliabilityGovernorEngine().evaluate()
    notifications = OperatorNotificationEngine().unread()
    events = OperatorEventBusEngine().recent(limit=10)
    quote_heartbeat = FastQuoteHeartbeatService.status()
    token_status = TradeStationTokenStatusEngine().evaluate()
    mission_readiness = _mission_readiness_score(reliability, governor, quote_heartbeat, token_status)

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
        "quote_heartbeat": quote_heartbeat,
        "token_status": token_status,
        "mission_readiness": mission_readiness,
        "master_decision": master_decision,
        "status": "OPERATOR_COCKPIT_STATUS_READY",
    }
