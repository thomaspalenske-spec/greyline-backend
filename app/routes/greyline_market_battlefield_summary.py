from fastapi import APIRouter

from app.routes.greyline_market_battlefield import greyline_market_battlefield
from app.services.market_battlefield_snapshot_cache import MarketBattlefieldSnapshotCache
from app.services.battlefield_history_engine import BattlefieldHistoryEngine

router = APIRouter()


@router.get("/greyline-market-battlefield-summary")
def greyline_market_battlefield_summary(force_refresh: bool = False):
    cached = MarketBattlefieldSnapshotCache.get()
    if cached is not None and force_refresh is False:
        cached["summary_mode"] = "CACHE_FAST"
        return cached

    if force_refresh is False:
        return {
            "snapshot_cache": {
                "cache_hit": False,
                "cache_available": False,
                "cache_mode": "CACHE_ONLY_NON_BLOCKING",
                "cache_instruction": "Run RUN_MARKET_BATTLEFIELD_SUMMARY_REFRESH_BACKGROUND to refresh cache.",
            },
            "system": "GreyLine",
            "battlefield_health": "UNKNOWN",
            "battlefield_health_reason": "No valid cached battlefield summary is available. Normal summary is non-blocking and will not run slow refresh inline.",
            "endpoint": "/greyline-market-battlefield-summary",
            "summary_mode": "CACHE_ONLY_NO_VALID_CACHE",
            "status": "GREYLINE_MARKET_BATTLEFIELD_SUMMARY_CACHE_EMPTY",
        }

    battlefield = greyline_market_battlefield()

    calls = battlefield.get("calls", {})
    puts = battlefield.get("puts", {})
    flow = battlefield.get("institutional_flow", {})
    decision = battlefield.get("master_decision", {})

    best_call = calls.get("best") or {}
    best_put = puts.get("best") or {}
    top_calls = battlefield.get("top_calls") or []
    top_puts = battlefield.get("top_puts") or []
    top_candidates = battlefield.get("top_candidates") or []
    call_flow = calls.get("best_flow_confirmation") or {}
    put_flow = puts.get("best_flow_confirmation") or {}

    ready_call_count = calls.get("ready_count") or 0
    ready_put_count = puts.get("ready_count") or 0
    direct_flow_ready = flow.get("direct_ready") is True

    actionable_candidates = [
        c for c in [best_call, best_put]
        if (c or {}).get("result") == "EXECUTE"
    ]

    if actionable_candidates:
        battlefield_master_decision = "EXECUTE_SIGNAL_BLOCKED_READ_ONLY"
        battlefield_master_reason = "Battlefield best candidate is EXECUTE; live order placement remains disabled."
    else:
        battlefield_master_decision = decision.get("decision")
        battlefield_master_reason = decision.get("reason")

    master_decision = battlefield_master_decision

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
        "battlefield_started_at": battlefield.get("battlefield_started_at"),
        "battlefield_completed_at": battlefield.get("battlefield_completed_at"),
        "battlefield_timings": battlefield.get("battlefield_timings"),
        "directional_dashboard_started_at": battlefield.get("directional_dashboard_started_at"),
        "directional_dashboard_completed_at": battlefield.get("directional_dashboard_completed_at"),
        "directional_dashboard_timings": battlefield.get("directional_dashboard_timings"),
        "opportunity_scoring_timings": battlefield.get("opportunity_scoring_timings"),
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
            "composite_score": best_call.get("composite_score"),
            "option_type": best_call.get("option_type"),
            "directional_bias": best_call.get("directional_bias"),
            "direction_confidence": best_call.get("direction_confidence"),
            "liquidity_score": best_call.get("liquidity_score"),
            "setup_score": best_call.get("setup_score"),
            "bullish_setup_score": best_call.get("bullish_setup_score"),
            "bearish_setup_score": best_call.get("bearish_setup_score"),
            "flow_confirmation": call_flow.get("confirmation"),
            "flow_strength": call_flow.get("flow_strength"),
            "premium_flow": call_flow.get("premium_flow"),
            "signal_age_days": BattlefieldHistoryEngine._signal_age_days(
                best_call.get("symbol"),
                best_call.get("option_type"),
            ),
        },
        "best_put": {
            "symbol": best_put.get("symbol"),
            "result": best_put.get("result"),
            "score": best_put.get("composite_score"),
            "composite_score": best_put.get("composite_score"),
            "option_type": best_put.get("option_type"),
            "directional_bias": best_put.get("directional_bias"),
            "direction_confidence": best_put.get("direction_confidence"),
            "liquidity_score": best_put.get("liquidity_score"),
            "setup_score": best_put.get("setup_score"),
            "bullish_setup_score": best_put.get("bullish_setup_score"),
            "bearish_setup_score": best_put.get("bearish_setup_score"),
            "flow_confirmation": put_flow.get("confirmation"),
            "flow_strength": put_flow.get("flow_strength"),
            "premium_flow": put_flow.get("premium_flow"),
            "signal_age_days": BattlefieldHistoryEngine._signal_age_days(
                best_put.get("symbol"),
                best_put.get("option_type"),
            ),
        },
        "top_calls": top_calls,
        "top_puts": top_puts,
        "top_candidates": top_candidates,
        "institutional_flow_mode": flow.get("mode"),
        "direct_institutional_flow_ready": flow.get("direct_ready"),
        "missing_high_priority_flow_feeds": flow.get("missing_high_priority_feeds"),
        "master_decision": battlefield_master_decision,
        "master_reason": battlefield_master_reason,
        "summary_mode": "FORCE_REFRESH" if force_refresh else "CACHE_MISS_REFRESH",
        "status": "GREYLINE_MARKET_BATTLEFIELD_SUMMARY_READY",
    }

    try:
        BattlefieldHistoryEngine.record(snapshot)
    except Exception:
        pass

    return MarketBattlefieldSnapshotCache.set(snapshot)
