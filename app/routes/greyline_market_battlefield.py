from fastapi import APIRouter

from app.routes.directional_readiness_dashboard import directional_readiness_dashboard
from app.routes.flow_feed_readiness_report import flow_feed_readiness_report
from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine

router = APIRouter()


@router.get("/greyline-market-battlefield")
def greyline_market_battlefield():
    readiness = directional_readiness_dashboard()
    flow = flow_feed_readiness_report()
    decision = GreyLineMasterDecisionEngine().evaluate()

    return {
        "system": "GreyLine",
        "endpoint": "/greyline-market-battlefield",
        "purpose": "One-screen commander view of market direction, readiness, institutional-flow limitations, and master decision.",
        "market_bias": readiness.get("opportunity_bias"),
        "symbols_scored": readiness.get("symbols_scored"),
        "calls": {
            "count": readiness.get("call_count"),
            "ready_count": readiness.get("ready_call_count"),
            "best": readiness.get("best_call"),
            "best_readiness": readiness.get("best_call_readiness"),
            "best_flow_confirmation": readiness.get("best_call_flow_confirmation"),
        },
        "puts": {
            "count": readiness.get("put_count"),
            "ready_count": readiness.get("ready_put_count"),
            "best": readiness.get("best_put"),
            "best_readiness": readiness.get("best_put_readiness"),
            "best_flow_confirmation": readiness.get("best_put_flow_confirmation"),
        },
        "institutional_flow": {
            "mode": flow.get("current_flow_mode"),
            "direct_ready": flow.get("direct_institutional_flow_ready"),
            "judgment": flow.get("readiness_judgment"),
            "missing_high_priority_feeds": flow.get("high_priority_missing_feeds"),
        },
        "master_decision": {
            "decision": decision.get("decision"),
            "reason": decision.get("decision_reason"),
            "top_candidate": decision.get("top_candidate"),
            "execution_enabled": decision.get("execution_enabled"),
            "order_placement_allowed": decision.get("order_placement_allowed"),
        },
        "status": "GREYLINE_MARKET_BATTLEFIELD_READY",
    }
