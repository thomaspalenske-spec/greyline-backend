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
                "bullish_setup_score": item.get("bullish_setup_score"),
                "bearish_setup_score": item.get("bearish_setup_score"),
                "regime": item.get("regime"),
                "regime_score": item.get("regime_score"),
                "risk_state": item.get("risk_state"),
                "risk_state_score": item.get("risk_state_score"),
                "breadth_score": item.get("breadth_score"),
                "asymmetry_score": item.get("asymmetry_score"),
                "volatility_score": item.get("volatility_score"),
                "institutional_sponsorship_score": item.get(
                    "institutional_sponsorship_score"
                ),
                "institutional_forecast_confidence": item.get(
                    "institutional_forecast_confidence"
                ),
                "institutional_calibrated_forecast_confidence": item.get(
                    "institutional_calibrated_forecast_confidence"
                ),
                "institutional_forecast_trust_state": item.get(
                    "institutional_forecast_trust_state"
                ),
                "adaptive_institutional_weighting": item.get(
                    "adaptive_institutional_weighting"
                ),
                "institutional_forecast": item.get(
                    "institutional_forecast"
                ),
                "institutional_forecast_verification": item.get(
                    "institutional_forecast_verification"
                ),
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
