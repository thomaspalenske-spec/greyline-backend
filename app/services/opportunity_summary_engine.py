from datetime import datetime

from app.services.opportunity_scoring_engine import OpportunityScoringEngine


class OpportunitySummaryEngine:

    def get_summary(self, limit=None):
        scoring = OpportunityScoringEngine().score_opportunities(limit=limit)

        rows = []

        for item in scoring.get("opportunities", []):
            rows.append({
                "symbol": item.get("symbol"),
                "result": item.get("result"),
                "composite_score": item.get("composite_score"),
                "bullish_score": item.get("bullish_score"),
                "bearish_score": item.get("bearish_score"),
                "opposing_score": item.get("opposing_score"),
                "directional_bias": item.get("directional_bias"),
                "option_type": item.get("option_type"),
                "direction_confidence": item.get("direction_confidence"),
                "liquidity_score": item.get("liquidity_score"),
                "setup_score": item.get("setup_score"),
                "order_placement_allowed": item.get("order_placement_allowed"),
                "governor_status": item.get("governor_status")
            })

        rows = sorted(rows, key=lambda x: x.get("composite_score") or 0, reverse=True)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols_scored": len(rows),
            "opportunity_scoring_timings": scoring.get("opportunity_scoring_timings"),
            "opportunities": rows,
            "execution_enabled": False,
            "status": "OPPORTUNITY_SUMMARY_READY"
        }
