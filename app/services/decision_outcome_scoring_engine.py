from datetime import datetime

from app.services.forward_outcome_capture_engine import ForwardOutcomeCaptureEngine


class DecisionOutcomeScoringEngine:

    def score(self, limit=50):
        captured = ForwardOutcomeCaptureEngine().capture(limit=limit)
        captures = captured.get("captures", [])

        scored = []

        favorable_count = 0
        unfavorable_count = 0
        neutral_count = 0
        pending_count = 0
        skipped_count = 0

        for item in captures:
            symbol = item.get("symbol")
            decision = item.get("decision")
            capture_status = item.get("capture_status")

            if capture_status != "FORWARD_OUTCOME_CAPTURED" or not symbol:
                skipped_count += 1
                scored.append({
                    "decision_timestamp": item.get("decision_timestamp"),
                    "symbol": symbol,
                    "decision": decision,
                    "score_status": "SKIPPED",
                    "score_result": item.get("capture_status"),
                    "score_reason": item.get("capture_reason", "No captured forward quote available"),
                    "execution_enabled": False,
                    "order_placement_allowed": False,
                })
                continue

            try:
                last = float(item.get("last"))
                previous_close = float(item.get("previous_close"))
                move_pct = round(((last - previous_close) / previous_close) * 100, 4)
            except Exception:
                pending_count += 1
                scored.append({
                    "decision_timestamp": item.get("decision_timestamp"),
                    "symbol": symbol,
                    "decision": decision,
                    "score_status": "PENDING",
                    "score_result": "PRICE_DATA_INCOMPLETE",
                    "score_reason": "Captured quote missing last or previous_close",
                    "execution_enabled": False,
                    "order_placement_allowed": False,
                })
                continue

            if decision == "EXECUTE_SIGNAL_BLOCKED_READ_ONLY":
                if move_pct >= 1.0:
                    score_result = "FAVORABLE_EXECUTE_SIGNAL"
                    score_reason = "Price moved at least +1% versus previous close"
                    favorable_count += 1
                elif move_pct <= -1.0:
                    score_result = "UNFAVORABLE_EXECUTE_SIGNAL"
                    score_reason = "Price moved at least -1% versus previous close"
                    unfavorable_count += 1
                else:
                    score_result = "NEUTRAL_EXECUTE_SIGNAL"
                    score_reason = "Price move stayed inside +/-1% neutral band"
                    neutral_count += 1
            else:
                score_result = "NON_EXECUTE_DECISION_PENDING_RULES"
                score_reason = "Scoring rules for this decision type are not yet active"
                pending_count += 1

            scored.append({
                "decision_timestamp": item.get("decision_timestamp"),
                "capture_timestamp": item.get("capture_timestamp"),
                "symbol": symbol,
                "decision": decision,
                "last": item.get("last"),
                "previous_close": item.get("previous_close"),
                "move_pct": move_pct,
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
