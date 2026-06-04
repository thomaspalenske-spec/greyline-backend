from datetime import datetime

from app.services.opportunity_scoring_engine import OpportunityScoringEngine


class OpportunitySummaryEngine:

    def get_summary(self):
        scoring = OpportunityScoringEngine().score_opportunities()

        rows = []

        for item in scoring.get("opportunities", []):
            rows.append({
                "symbol": item.get("symbol"),
                "result": item.get("result"),
                "composite_score": item.get("composite_score"),
                "liquidity_score": item.get("liquidity_score"),
                "setup_score": item.get("setup_score"),
                "order_placement_allowed": item.get("order_placement_allowed"),
                "governor_status": item.get("governor_status")
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols_scored": len(rows),
            "opportunities": rows,
            "execution_enabled": False,
            "status": "OPPORTUNITY_SUMMARY_READY"
        }
