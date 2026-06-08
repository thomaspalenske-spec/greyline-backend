from datetime import datetime

from app.services.decision_outcome_scoring_engine import DecisionOutcomeScoringEngine


class DecisionLearningEngine:

    def analyze(self, limit=50):
        scoring = DecisionOutcomeScoringEngine().score(limit=limit)

        recommendations = []
        learning_events = 0
        reduce_confidence_count = 0
        increase_confidence_count = 0
        hold_confidence_count = 0

        for item in scoring.get("scored_outcomes", []):
            if item.get("score_status") != "SCORED":
                continue

            learning_events += 1
            symbol = item.get("symbol")
            result = item.get("score_result")

            if result == "UNFAVORABLE_EXECUTE_SIGNAL":
                adjustment = "REDUCE_CONFIDENCE"
                rationale = "Read-only execute signal produced unfavorable forward outcome"
                reduce_confidence_count += 1
            elif result == "FAVORABLE_EXECUTE_SIGNAL":
                adjustment = "INCREASE_CONFIDENCE"
                rationale = "Read-only execute signal produced favorable forward outcome"
                increase_confidence_count += 1
            else:
                adjustment = "HOLD_CONFIDENCE"
                rationale = "Outcome was neutral or inconclusive"
                hold_confidence_count += 1

            recommendations.append({
                "decision_timestamp": item.get("decision_timestamp"),
                "symbol": symbol,
                "decision": item.get("decision"),
                "score_result": result,
                "move_pct": item.get("move_pct"),
                "learning_adjustment": adjustment,
                "learning_rationale": rationale,
                "execution_enabled": False,
                "order_placement_allowed": False,
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_LEARNING_ENGINE",
            "learning_events": learning_events,
            "reduce_confidence_count": reduce_confidence_count,
            "increase_confidence_count": increase_confidence_count,
            "hold_confidence_count": hold_confidence_count,
            "recommendations": recommendations,
            "automatic_weight_changes_enabled": False,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_LEARNING_READY",
        }
