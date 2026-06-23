from datetime import datetime

from app.services.battlefield_history_engine import BattlefieldHistoryEngine


class BattlefieldVelocityEngine:

    def evaluate(self, symbol):
        history = BattlefieldHistoryEngine.load(limit=500)

        points = []

        for row in history:
            for side in ["best_call", "best_put"]:
                item = row.get(side) or {}

                if item.get("symbol") == symbol:
                    score = item.get("composite_score")

                    if score is not None:
                        points.append({
                            "timestamp": row.get("timestamp"),
                            "score": float(score)
                        })

        if len(points) < 2:
            return {
                "symbol": symbol,
                "velocity": 0,
                "trend": "INSUFFICIENT_DATA",
                "status": "BATTLEFIELD_VELOCITY_READY"
            }

        first = points[0]["score"]
        last = points[-1]["score"]

        velocity = round(last - first, 2)

        return {
            "symbol": symbol,
            "first_score": first,
            "latest_score": last,
            "velocity": velocity,
            "trend": (
                "IMPROVING"
                if velocity > 0
                else "DETERIORATING"
                if velocity < 0
                else "FLAT"
            ),
            "samples": len(points),
            "status": "BATTLEFIELD_VELOCITY_READY"
        }
