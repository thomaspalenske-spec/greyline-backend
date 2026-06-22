from fastapi import APIRouter

from app.services.opportunity_summary_engine import OpportunitySummaryEngine
from app.services.opportunity_symmetry_engine import OpportunitySymmetryEngine
from app.services.bear_market_opportunity_engine import BearMarketOpportunityEngine
from app.services.put_readiness_gate_engine import PutReadinessGateEngine
from app.services.call_readiness_gate_engine import CallReadinessGateEngine

router = APIRouter()


@router.get("/directional-opportunity-report")
def directional_opportunity_report():
    summary = OpportunitySummaryEngine().get_summary(limit=50)
    opportunities = summary.get("opportunities", [])

    calls = [
        item for item in opportunities
        if item.get("option_type") == "CALL" or item.get("directional_bias") == "BULLISH"
    ]

    puts = [
        item for item in opportunities
        if item.get("option_type") == "PUT" or item.get("directional_bias") == "BEARISH"
    ]

    calls = sorted(calls, key=lambda x: x.get("composite_score") or 0, reverse=True)
    puts = sorted(puts, key=lambda x: x.get("composite_score") or 0, reverse=True)

    symmetry = OpportunitySymmetryEngine().evaluate(opportunities)
    bear = BearMarketOpportunityEngine().evaluate(opportunities)

    put_readiness_rows = [
        PutReadinessGateEngine().evaluate(item)
        for item in puts[:10]
    ]

    call_readiness_rows = [
        CallReadinessGateEngine().evaluate(item)
        for item in calls[:10]
    ]

    put_blocker_distribution = {}
    for row in put_readiness_rows:
        count = len(row.get("blockers", []))
        key = f"{count}_blockers"
        put_blocker_distribution[key] = put_blocker_distribution.get(key, 0) + 1

    call_blocker_distribution = {}
    for row in call_readiness_rows:
        count = len(row.get("blockers", []))
        key = f"{count}_blockers"
        call_blocker_distribution[key] = call_blocker_distribution.get(key, 0) + 1

    return {
        "system": "GreyLine",
        "endpoint": "/directional-opportunity-report",
        "purpose": "Compact call versus put opportunity report.",
        "symbols_scored": summary.get("symbols_scored"),
        "call_count": len(calls),
        "put_count": len(puts),
        "opportunity_bias": symmetry.get("opportunity_bias"),
        "call_execute_count": len([x for x in calls if x.get("result") == "EXECUTE"]),
        "put_execute_count": len([x for x in puts if x.get("result") == "EXECUTE"]),
        "call_watch_count": len([x for x in calls if x.get("result") == "WATCH"]),
        "put_watch_count": len([x for x in puts if x.get("result") == "WATCH"]),
        "best_call": calls[0] if calls else None,
        "best_call_readiness": CallReadinessGateEngine().evaluate(calls[0] if calls else None),
        "call_readiness_summary": {
            "calls_evaluated": len(call_readiness_rows),
            "call_blocker_distribution": call_blocker_distribution,
            "call_ready_count": len([x for x in call_readiness_rows if x.get("call_ready_for_execute") is True]),
            "call_not_ready_count": len([x for x in call_readiness_rows if x.get("call_ready_for_execute") is False]),
        },
        "top_call_readiness": call_readiness_rows[:5],
        "closest_call_to_ready": sorted(
            call_readiness_rows,
            key=lambda x: len(x.get("blockers", []))
        )[0] if calls else None,
        "best_put": puts[0] if puts else None,
        "best_put_readiness": PutReadinessGateEngine().evaluate(puts[0] if puts else None),
        "put_readiness_summary": {
            "puts_evaluated": len(put_readiness_rows),
            "put_blocker_distribution": put_blocker_distribution,
            "put_ready_count": len([x for x in put_readiness_rows if x.get("put_ready_for_execute") is True]),
            "put_not_ready_count": len([x for x in put_readiness_rows if x.get("put_ready_for_execute") is False]),
        },
        "top_put_readiness": put_readiness_rows[:5],
        "closest_put_to_ready": sorted(
            put_readiness_rows,
            key=lambda x: len(x.get("blockers", []))
        )[0] if puts else None,
        "best_bearish_candidate": bear.get("best_bearish_candidate"),
        "top_calls": calls[:5],
        "top_puts": puts[:5],
        "status": "DIRECTIONAL_OPPORTUNITY_REPORT_READY",
    }
