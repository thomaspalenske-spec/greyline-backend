from datetime import datetime


class DecisionExplainabilityEngine:
    def evaluate(self, summary):
        top = summary.get("top_candidate") or {}

        decision = summary.get("decision") or "NO_CANDIDATE"
        score = float(top.get("adjusted_score") or 0)
        liquidity = float(top.get("liquidity_score") or 0)
        reliability = float(top.get("signal_reliability_score") or 0)
        grade = top.get("signal_reliability_grade") or "UNKNOWN"
        confidence = float(top.get("direction_confidence") or 0)
        strength = float(top.get("signal_strength_score") or 0)
        allocation_score = float(top.get("portfolio_allocation_score") or 0)

        passed = []
        failed = []

        if score >= 85:
            passed.append(f"Execute score met ({score} >= 85)")
        else:
            failed.append(f"Execute score below threshold ({score} < 85)")

        if liquidity >= 70:
            passed.append(f"Liquidity available ({liquidity} >= 70)")
        else:
            failed.append(f"Liquidity below threshold ({liquidity} < 70)")

        if strength >= 80 or top.get("signal_state") == "FRESH":
            passed.append(f"Signal fresh ({top.get('signal_state') or strength})")
        else:
            failed.append(f"Signal not fresh ({top.get('signal_state') or strength})")

        if grade in ["A", "B"] or reliability >= 80:
            passed.append(f"Reliability acceptable ({grade} / {reliability})")
        else:
            failed.append(f"Reliability below deployment grade ({grade} / {reliability})")

        if confidence >= 50:
            passed.append(f"Direction confidence acceptable ({confidence} >= 50)")
        else:
            failed.append(f"Direction confidence below threshold ({confidence} < 50)")

        if not top:
            primary_blocker = "No candidate available"
            next_event_needed = "Wait for a valid candidate"
        elif confidence < 50:
            primary_blocker = "Direction confidence below deployment threshold"
            next_event_needed = "Increase direction confidence above 50"
        elif grade not in ["A", "B"] and reliability < 80:
            primary_blocker = "Signal reliability below deployment threshold"
            next_event_needed = "Improve reliability to B or better"
        elif decision != "DEPLOY":
            primary_blocker = decision
            next_event_needed = "Wait for portfolio governor to authorize deployment"
        else:
            primary_blocker = "None"
            next_event_needed = "Deployment authorized"

        readiness = round(
            min(100, max(0,
                (min(score, 100) * 0.30) +
                (min(liquidity, 100) * 0.20) +
                (min(reliability, 100) * 0.25) +
                (min(confidence, 100) * 0.15) +
                (min(strength, 100) * 0.10)
            )),
            2
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "DecisionExplainabilityEngine",
            "decision": decision,
            "symbol": top.get("symbol"),
            "option_type": top.get("option_type"),
            "allocation_score": allocation_score,
            "deployment_ready": decision == "DEPLOY",
            "estimated_readiness": readiness,
            "passed": passed,
            "failed": failed,
            "primary_blocker": primary_blocker,
            "next_event_needed": next_event_needed,
            "status": "DECISION_EXPLAINABILITY_READY",
        }
