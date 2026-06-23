from datetime import datetime


class WhyNotReadyEngine:

    def evaluate(self, opportunity_queue):

        candidate = opportunity_queue.get("top_candidate")

        if not candidate:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "ready": False,
                "blockers": ["NO_CANDIDATE"],
                "status": "WHY_NOT_READY_READY",
            }

        blockers = []

        score_distance = candidate.get(
            "score_distance_to_execute",
            999
        )

        liquidity_distance = candidate.get(
            "liquidity_distance_to_execute",
            999
        )

        try:
            score_distance = float(score_distance)
        except (TypeError, ValueError):
            score_distance = 999

        liquidity_available = liquidity_distance not in [None, "None", "null", "NULL", ""]
        try:
            liquidity_distance = float(liquidity_distance)
        except (TypeError, ValueError):
            liquidity_available = False
            liquidity_distance = 0

        if score_distance > 0:
            blockers.append(
                f"SCORE_SHORT_BY_{round(score_distance,2)}"
            )

        if not liquidity_available:
            blockers.append("LIQUIDITY_UNAVAILABLE")
        elif liquidity_distance > 0:
            blockers.append(
                f"LIQUIDITY_SHORT_BY_{round(liquidity_distance,2)}"
            )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": candidate.get("symbol"),
            "ready": len(blockers) == 0,
            "blockers": blockers,
            "status": "WHY_NOT_READY_READY",
        }
