from fastapi import APIRouter

from app.services.opportunity_summary_engine import OpportunitySummaryEngine
from app.services.call_readiness_gate_engine import CallReadinessGateEngine
from app.services.put_readiness_gate_engine import PutReadinessGateEngine
from app.services.opportunity_symmetry_engine import OpportunitySymmetryEngine
from app.services.directional_flow_confirmation_engine import DirectionalFlowConfirmationEngine
from app.routes.flow_feed_readiness_report import flow_feed_readiness_report

router = APIRouter()


@router.get("/directional-readiness-dashboard")
def directional_readiness_dashboard():
    summary = OpportunitySummaryEngine().get_summary(limit=50)
    opportunities = summary.get("opportunities", [])

    calls = sorted(
        [
            item for item in opportunities
            if item.get("option_type") == "CALL" or item.get("directional_bias") == "BULLISH"
        ],
        key=lambda x: x.get("composite_score") or 0,
        reverse=True,
    )

    puts = sorted(
        [
            item for item in opportunities
            if item.get("option_type") == "PUT" or item.get("directional_bias") == "BEARISH"
        ],
        key=lambda x: x.get("composite_score") or 0,
        reverse=True,
    )

    call_readiness = [CallReadinessGateEngine().evaluate(item) for item in calls[:10]]
    put_readiness = [PutReadinessGateEngine().evaluate(item) for item in puts[:10]]

    ready_calls = [row for row in call_readiness if row.get("call_ready_for_execute") is True]
    ready_puts = [row for row in put_readiness if row.get("put_ready_for_execute") is True]

    closest_call = sorted(call_readiness, key=lambda x: len(x.get("blockers", [])))[0] if call_readiness else None
    closest_put = sorted(put_readiness, key=lambda x: len(x.get("blockers", [])))[0] if put_readiness else None

    symmetry = OpportunitySymmetryEngine().evaluate(opportunities)
    flow_feed_readiness = flow_feed_readiness_report()

    return {
        "system": "GreyLine",
        "endpoint": "/directional-readiness-dashboard",
        "purpose": "Commander-level call versus put readiness display.",
        "symbols_scored": summary.get("symbols_scored"),
        "opportunity_bias": symmetry.get("opportunity_bias"),
        "institutional_flow_warning": {
            "current_flow_mode": flow_feed_readiness.get("current_flow_mode"),
            "direct_institutional_flow_ready": flow_feed_readiness.get("direct_institutional_flow_ready"),
            "readiness_judgment": flow_feed_readiness.get("readiness_judgment"),
            "high_priority_missing_count": flow_feed_readiness.get("high_priority_missing_count"),
            "high_priority_missing_feeds": flow_feed_readiness.get("high_priority_missing_feeds"),
        },
        "call_count": len(calls),
        "put_count": len(puts),
        "ready_call_count": len(ready_calls),
        "ready_put_count": len(ready_puts),
        "best_call": calls[0] if calls else None,
        "best_put": puts[0] if puts else None,
        "best_call_readiness": call_readiness[0] if call_readiness else None,
        "best_call_flow_confirmation": DirectionalFlowConfirmationEngine().evaluate(calls[0] if calls else None),
        "best_put_readiness": put_readiness[0] if put_readiness else None,
        "best_put_flow_confirmation": DirectionalFlowConfirmationEngine().evaluate(puts[0] if puts else None),
        "closest_call_to_ready": closest_call,
        "closest_put_to_ready": closest_put,
        "ready_calls": ready_calls,
        "ready_puts": ready_puts,
        "ready_call_flow_confirmations": [
            DirectionalFlowConfirmationEngine().evaluate(calls[i])
            for i, row in enumerate(call_readiness)
            if row.get("call_ready_for_execute") is True and i < len(calls)
        ],
        "ready_put_flow_confirmations": [
            DirectionalFlowConfirmationEngine().evaluate(puts[i])
            for i, row in enumerate(put_readiness)
            if row.get("put_ready_for_execute") is True and i < len(puts)
        ],
        "status": "DIRECTIONAL_READINESS_DASHBOARD_READY",
    }
