from datetime import datetime


class BattlefieldReadinessTimerEngine:

    def evaluate(self, opportunity_queue):

        candidate = opportunity_queue.get("top_candidate")

        if not candidate:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "estimated_time_to_execute_hours": None,
                "confidence": "LOW",
                "status": "BATTLEFIELD_READINESS_TIMER_READY",
            }

        distance = candidate.get("score_distance_to_execute", 999)

        estimated_hours = round(distance * 6, 2)

        confidence = "LOW"

        if distance <= 1:
            confidence = "HIGH"
        elif distance <= 3:
            confidence = "MEDIUM"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": candidate.get("symbol"),
            "distance_to_execute": distance,
            "estimated_time_to_execute_hours": estimated_hours,
            "confidence": confidence,
            "status": "BATTLEFIELD_READINESS_TIMER_READY",
        }
