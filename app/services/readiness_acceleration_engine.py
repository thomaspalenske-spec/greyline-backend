from datetime import datetime

from app.services.battlefield_history_engine import BattlefieldHistoryEngine


class ReadinessAccelerationEngine:
    EXECUTE_SCORE = 85

    def evaluate(self, symbol=None):
        history = BattlefieldHistoryEngine().history(limit=100)

        points = []
        for row in history:
            for side in ["best_call", "best_put"]:
                item = row.get(side) or {}
                item_symbol = item.get("symbol")
                score = item.get("composite_score")

                if not item_symbol or score is None:
                    continue

                if symbol and item_symbol != symbol:
                    continue

                points.append({
                    "timestamp": row.get("timestamp"),
                    "symbol": item_symbol,
                    "side": side,
                    "score": float(score),
                    "liquidity_score": item.get("liquidity_score"),
                    "setup_score": item.get("setup_score"),
                    "directional_bias": item.get("directional_bias"),
                    "option_type": item.get("option_type"),
                })

        if len(points) < 2:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "trend": "INSUFFICIENT_HISTORY",
                "velocity": 0,
                "acceleration": 0,
                "status": "READINESS_ACCELERATION_READY",
            }

        latest = points[-1]
        previous = points[-2]
        first = points[0]

        velocity = round(latest["score"] - previous["score"], 2)
        total_velocity = round(latest["score"] - first["score"], 2)

        if len(points) >= 3:
            prior_velocity = points[-2]["score"] - points[-3]["score"]
            acceleration = round(velocity - prior_velocity, 2)
        else:
            acceleration = 0

        distance_to_execute = round(max(0, self.EXECUTE_SCORE - latest["score"]), 2)

        if distance_to_execute == 0:
            trend = "EXECUTE_READY"
        elif velocity > 0 and acceleration >= 0 and distance_to_execute <= 10:
            trend = "APPROACHING_EXECUTE_FAST"
        elif velocity > 0:
            trend = "IMPROVING"
        elif velocity < 0:
            trend = "DETERIORATING"
        else:
            trend = "STABLE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": latest["symbol"],
            "option_type": latest.get("option_type"),
            "directional_bias": latest.get("directional_bias"),
            "latest_score": latest["score"],
            "previous_score": previous["score"],
            "first_score": first["score"],
            "distance_to_execute": distance_to_execute,
            "velocity": velocity,
            "total_velocity": total_velocity,
            "acceleration": acceleration,
            "trend": trend,
            "samples": len(points),
            "status": "READINESS_ACCELERATION_READY",
        }
