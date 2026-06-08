from datetime import datetime

from app.services.decision_outcome_scoring_engine import DecisionOutcomeScoringEngine
from app.services.master_decision_history_engine import MasterDecisionHistoryEngine


class DecisionFeatureAttributionEngine:

    def analyze(self, limit=50):
        scoring = DecisionOutcomeScoringEngine().score(limit=limit)
        history = MasterDecisionHistoryEngine().get_history(limit=limit)

        events_by_timestamp = {
            event.get("timestamp"): event
            for event in history.get("events", [])
        }

        attributions = []
        failure_factors = {}
        success_factors = {}

        for scored in scoring.get("scored_outcomes", []):
            decision_timestamp = scored.get("decision_timestamp")
            source_event = events_by_timestamp.get(decision_timestamp, {})
            top_candidate = source_event.get("top_candidate") or {}

            factors = {
                "composite_score": top_candidate.get("composite_score"),
                "market_data_score": top_candidate.get("market_data_score"),
                "liquidity_score": top_candidate.get("liquidity_score"),
                "setup_score": top_candidate.get("setup_score"),
                "regime_score": top_candidate.get("regime_score"),
                "regime": top_candidate.get("regime"),
                "volatility_score": top_candidate.get("volatility_score"),
                "expected_value_score": top_candidate.get("expected_value_score"),
                "trend_persistence_score": top_candidate.get("trend_persistence_score"),
                "breadth_score": top_candidate.get("breadth_score"),
                "institutional_sponsorship_score": top_candidate.get("institutional_sponsorship_score"),
                "asymmetry_score": top_candidate.get("asymmetry_score"),
                "risk_state_score": top_candidate.get("risk_state_score"),
                "risk_state": top_candidate.get("risk_state"),
            }

            score_result = scored.get("score_result")

            if score_result == "UNFAVORABLE_EXECUTE_SIGNAL":
                for key, value in factors.items():
                    if value is not None:
                        failure_factors[key] = failure_factors.get(key, 0) + 1

            if score_result == "FAVORABLE_EXECUTE_SIGNAL":
                for key, value in factors.items():
                    if value is not None:
                        success_factors[key] = success_factors.get(key, 0) + 1

            attributions.append({
                "decision_timestamp": decision_timestamp,
                "symbol": scored.get("symbol"),
                "decision": scored.get("decision"),
                "score_result": score_result,
                "move_pct": scored.get("move_pct"),
                "factors": factors,
                "execution_enabled": False,
                "order_placement_allowed": False,
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_FEATURE_ATTRIBUTION",
            "events_analyzed": len(attributions),
            "failure_factor_counts": failure_factors,
            "success_factor_counts": success_factors,
            "attributions": attributions,
            "automatic_weight_changes_enabled": False,
            "human_approval_required": True,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_FEATURE_ATTRIBUTION_READY",
        }
