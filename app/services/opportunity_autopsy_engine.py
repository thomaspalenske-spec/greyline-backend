from datetime import datetime


class OpportunityAutopsyEngine:
    def evaluate(self, queue):
        rows = queue or []
        rejected = [r for r in rows if (r.get("result") != "EXECUTE")]

        if not rejected:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "autopsy_available": False,
                "reason": "NO_REJECTED_CANDIDATES",
                "status": "OPPORTUNITY_AUTOPSY_READY",
            }

        item = sorted(
            rejected,
            key=lambda x: (
                x.get("score_distance_to_execute", 999),
                -(x.get("score") or 0)
            )
        )[0]

        blockers = []
        if (item.get("score") or 0) < (item.get("execute_score_threshold") or 85):
            blockers.append("SCORE_BELOW_EXECUTE_THRESHOLD")
        if item.get("liquidity_score") is not None and item.get("liquidity_score") < (item.get("execute_liquidity_threshold") or 70):
            blockers.append("LIQUIDITY_BELOW_EXECUTE_THRESHOLD")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "autopsy_available": True,
            "symbol": item.get("symbol"),
            "option_type": item.get("option_type"),
            "result": item.get("result"),
            "score": item.get("score"),
            "score_distance_to_execute": item.get("score_distance_to_execute"),
            "liquidity_score": item.get("liquidity_score"),
            "setup_score": item.get("setup_score"),
            "direction_confidence": item.get("direction_confidence"),
            "blockers": blockers,
            "status": "OPPORTUNITY_AUTOPSY_READY",
        }
