from fastapi import APIRouter
from datetime import datetime

from app.routes.directional_readiness_dashboard import directional_readiness_dashboard
from app.routes.flow_feed_readiness_report import flow_feed_readiness_report
from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine

router = APIRouter()


@router.get("/greyline-market-battlefield")
def greyline_market_battlefield(include_master_decision: bool = False):
    TradeStationQuoteLiveEngine.clear_cache()
    battlefield_started_at = datetime.utcnow()
    timings = {}

    t0 = datetime.utcnow()
    readiness = directional_readiness_dashboard()
    t1 = datetime.utcnow()
    timings["directional_readiness_dashboard_seconds"] = round((t1 - t0).total_seconds(), 2)

    t0 = datetime.utcnow()
    flow = flow_feed_readiness_report()
    t1 = datetime.utcnow()
    timings["flow_feed_readiness_report_seconds"] = round((t1 - t0).total_seconds(), 2)

    if include_master_decision:
        t0 = datetime.utcnow()
        decision = GreyLineMasterDecisionEngine().evaluate()
        t1 = datetime.utcnow()
        timings["master_decision_engine_seconds"] = round((t1 - t0).total_seconds(), 2)
        master_decision = {
            "decision": decision.get("decision"),
            "reason": decision.get("decision_reason"),
            "top_candidate": decision.get("top_candidate"),
            "execution_enabled": decision.get("execution_enabled"),
            "order_placement_allowed": decision.get("order_placement_allowed"),
            "mode": "FULL_MASTER_DECISION_INCLUDED",
        }
    else:
        timings["master_decision_engine_seconds"] = 0
        master_decision = {
            "decision": "SKIPPED_FAST_BATTLEFIELD",
            "reason": "Master decision skipped to keep battlefield refresh fast. Use RUN_MASTER_DECISION for full decision.",
            "top_candidate": None,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "mode": "FAST_BATTLEFIELD_MASTER_DECISION_SKIPPED",
        }

    battlefield_completed_at = datetime.utcnow()
    timings["total_battlefield_seconds"] = round((battlefield_completed_at - battlefield_started_at).total_seconds(), 2)

    return {
        "system": "GreyLine",
        "endpoint": "/greyline-market-battlefield",
        "purpose": "One-screen commander view of market direction, readiness, institutional-flow limitations, and master decision.",
        "include_master_decision": include_master_decision,
        "battlefield_started_at": battlefield_started_at.isoformat(),
        "battlefield_completed_at": battlefield_completed_at.isoformat(),
        "battlefield_timings": timings,
        "directional_dashboard_started_at": readiness.get("dashboard_started_at"),
        "directional_dashboard_completed_at": readiness.get("dashboard_completed_at"),
        "directional_dashboard_timings": readiness.get("dashboard_timings"),
        "opportunity_scoring_timings": readiness.get("opportunity_scoring_timings"),
        "market_bias": readiness.get("opportunity_bias"),
        "symbols_scored": readiness.get("symbols_scored"),
        "calls": {
            "count": readiness.get("call_count"),
            "ready_count": readiness.get("ready_call_count"),
            "best": readiness.get("best_call"),
            "top": readiness.get("top_calls"),
            "best_readiness": readiness.get("best_call_readiness"),
            "best_flow_confirmation": readiness.get("best_call_flow_confirmation"),
        },
        "puts": {
            "count": readiness.get("put_count"),
            "ready_count": readiness.get("ready_put_count"),
            "best": readiness.get("best_put"),
            "top": readiness.get("top_puts"),
            "best_readiness": readiness.get("best_put_readiness"),
            "best_flow_confirmation": readiness.get("best_put_flow_confirmation"),
        },
        "top_calls": readiness.get("top_calls"),
        "top_puts": readiness.get("top_puts"),
        "top_candidates": readiness.get("top_candidates"),
        "institutional_flow": {
            "mode": flow.get("current_flow_mode"),
            "direct_ready": flow.get("direct_institutional_flow_ready"),
            "judgment": flow.get("readiness_judgment"),
            "missing_high_priority_feeds": flow.get("high_priority_missing_feeds"),
        },
        "master_decision": master_decision,
        "status": "GREYLINE_MARKET_BATTLEFIELD_READY",
    }
