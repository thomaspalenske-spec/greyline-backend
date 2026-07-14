from datetime import datetime

from app.services.forward_outcome_capture_engine import ForwardOutcomeCaptureEngine


class DecisionOutcomeScoringEngine:

    def score(self, limit=50):
        captured = ForwardOutcomeCaptureEngine().capture(limit=limit)
        # ForwardOutcomeCaptureEngine emits its per-record list under "outcomes",
        # with a directional schema (outcome_state / directional_return_pct /
        # directional_bias). Score against that; the capture engine has already
        # computed the directionally-adjusted return, so we classify off it.
        outcomes = captured.get("outcomes", [])

        scored = []

        favorable_count = 0
        unfavorable_count = 0
        neutral_count = 0
        pending_count = 0
        skipped_count = 0

        for item in outcomes:
            symbol = item.get("symbol")
            decision = item.get("candidate_result")
            decision_timestamp = item.get("candidate_timestamp")
            directional_return_pct = item.get("directional_return_pct")

            if item.get("outcome_state") != "PRICE_CAPTURED" or not symbol:
                skipped_count += 1
                scored.append({
                    "decision_timestamp": decision_timestamp,
                    "symbol": symbol,
                    "decision": decision,
                    "score_status": "SKIPPED",
                    "score_result": item.get("outcome_state"),
                    "score_reason": "No captured forward price available",
                    "execution_enabled": False,
                    "order_placement_allowed": False,
                })
                continue

            if directional_return_pct is None:
                pending_count += 1
                scored.append({
                    "decision_timestamp": decision_timestamp,
                    "symbol": symbol,
                    "decision": decision,
                    "score_status": "PENDING",
                    "score_result": "NON_DIRECTIONAL_OUTCOME_PENDING_RULES",
                    "score_reason": "Outcome lacks a directional bias to score",
                    "execution_enabled": False,
                    "order_placement_allowed": False,
                })
                continue

            if directional_return_pct >= 1.0:
                score_result = "FAVORABLE_EXECUTE_SIGNAL"
                score_reason = "Directional move at least +1% in the predicted direction"
                favorable_count += 1
            elif directional_return_pct <= -1.0:
                score_result = "UNFAVORABLE_EXECUTE_SIGNAL"
                score_reason = "Directional move at least -1% against the predicted direction"
                unfavorable_count += 1
            else:
                score_result = "NEUTRAL_EXECUTE_SIGNAL"
                score_reason = "Directional move stayed inside +/-1% neutral band"
                neutral_count += 1

            scored.append({
                "decision_timestamp": decision_timestamp,
                "capture_timestamp": item.get("timestamp"),
                "symbol": symbol,
                "decision": decision,
                "directional_bias": item.get("directional_bias"),
                "snapshot_price": item.get("snapshot_price"),
                "current_price": item.get("current_price"),
                "move_pct": directional_return_pct,
                "score_status": "SCORED",
                "score_result": score_result,
                "score_reason": score_reason,
                "execution_enabled": False,
                "order_placement_allowed": False,
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_OUTCOME_SCORING",
            "events_analyzed": len(scored),
            "favorable_count": favorable_count,
            "unfavorable_count": unfavorable_count,
            "neutral_count": neutral_count,
            "pending_count": pending_count,
            "skipped_count": skipped_count,
            "scored_outcomes": scored,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_OUTCOME_SCORING_READY",
        }
