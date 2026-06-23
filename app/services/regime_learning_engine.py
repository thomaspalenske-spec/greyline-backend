from collections import defaultdict
from datetime import datetime


class RegimeLearningEngine:
    def evaluate(self, one_hour_performance):
        rows = one_hour_performance.get("latest_scored") or []

        buckets = defaultdict(list)

        for r in rows:
            regime = r.get("regime") or "UNKNOWN"
            buckets[regime].append(float(r.get("directional_return_pct") or 0))

        leaderboard = []

        for regime, values in buckets.items():
            leaderboard.append({
                "regime": regime,
                "samples": len(values),
                "average_directional_return_pct": round(sum(values) / len(values), 4)
            })

        leaderboard.sort(
            key=lambda x: x["average_directional_return_pct"],
            reverse=True
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "RegimeLearningEngine",
            "record_count": sum(len(v) for v in buckets.values()),
            "regime_leaderboard": leaderboard,
            "status": "REGIME_LEARNING_READY"
        }
