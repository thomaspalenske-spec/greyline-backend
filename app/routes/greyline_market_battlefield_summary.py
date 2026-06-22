from fastapi import APIRouter

from app.routes.greyline_market_battlefield import greyline_market_battlefield
from app.services.market_battlefield_snapshot_cache import MarketBattlefieldSnapshotCache

router = APIRouter()


@router.get("/greyline-market-battlefield-summary")
def greyline_market_battlefield_summary():
    cached = MarketBattlefieldSnapshotCache.get()
    if cached is not None:
        return cached

    battlefield = greyline_market_battlefield()

    calls = battlefield.get("calls", {})
    puts = battlefield.get("puts", {})
    flow = battlefield.get("institutional_flow", {})
    decision = battlefield.get("master_decision", {})

    best_call = calls.get("best") or {}
    best_put = puts.get("best") or {}
    call_flow = calls.get("best_flow_confirmation") or {}
    put_flow = puts.get("best_flow_confirmation") or {}

    ready_call_count = calls.get("ready_count") or 0
    ready_put_count = puts.get("ready_count") or 0
    direct_flow_ready = flow.get("direct_ready") is True
    master_decision = decision.get("decision")

    if (ready_call_count > 0 or ready_put_count > 0) and direct_flow_ready:
        battlefield_health = "GREEN"
        battlefield_health_reason = "Actionable directional setup with direct institutional flow support."
    elif ready_call_count > 0 or ready_put_count > 0:
        battlefield_health = "YELLOW"
        battlefield_health_reason = "Actionable directional setup exists, but institutional flow is inferred only."
    elif master_decision in ["EXECUTE", "EXECUTE_SIGNAL_BLOCKED_READ_ONLY"]:
        battlefield_health = "YELLOW"
        battlefield_health_reason = "Master decision found an execute signal, but readiness or flow confirmation is incomplete."
    else:
        battlefield_health = "RED"
        battlefield_health_reason = "No ready directional setup."

    snapshot = {
        "system": "GreyLine",
        "battlefield_health": battlefield_health,
        "battlefield_health_reason": battlefield_health_reason,
        "endpoint": "/greyline-market-battlefield-summary",
        "market_bias": battlefield.get("market_bias"),
        "symbols_scored": battlefield.get("symbols_scored"),
        "call_count": calls.get("count"),
        "put_count": puts.get("count"),
        "ready_call_count": calls.get("ready_count"),
        "ready_put_count": puts.get("ready_count"),
        "best_call": {
            "symbol": best_call.get("symbol"),
            "result": best_call.get("result"),
            "score": best_call.get("composite_score"),
            "option_type": best_call.get("option_type"),
            "flow_confirmation": call_flow.get("confirmation"),
            "flow_strength": call_flow.get("flow_strength"),
        },
        "best_put": {
            "symbol": best_put.get("symbol"),
            "result": best_put.get("result"),
            "score": best_put.get("composite_score"),
            "option_type": best_put.get("option_type"),
            "flow_confirmation": put_flow.get("confirmation"),
            "flow_strength": put_flow.get("flow_strength"),
        },
        "institutional_flow_mode": flow.get("mode"),
        "direct_institutional_flow_ready": flow.get("direct_ready"),
        "missing_high_priority_flow_feeds": flow.get("missing_high_priority_feeds"),
        "master_decision": decision.get("decision"),
        "master_reason": decision.get("reason"),
        "status": "GREYLINE_MARKET_BATTLEFIELD_SUMMARY_READY",
    }

    return MarketBattlefieldSnapshotCache.set(snapshot)
