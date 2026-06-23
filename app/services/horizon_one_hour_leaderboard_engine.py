from datetime import datetime


class HorizonOneHourLeaderboardEngine:
    def _avg(self, rows):
        if not rows:
            return 0
        return round(
            sum(float(x.get("directional_return_pct") or 0) for x in rows) / len(rows),
            4
        )

    def _rank_bucket(self, rows, key_name):
        buckets = {}

        for row in rows or []:
            key = row.get(key_name) or "UNKNOWN"
            buckets.setdefault(key, []).append(row)

        ranked = [
            {
                key_name: key,
                "samples": len(items),
                "average_directional_return_pct": self._avg(items),
            }
            for key, items in buckets.items()
        ]

        return sorted(
            ranked,
            key=lambda x: x.get("average_directional_return_pct", 0),
            reverse=True,
        )

    def evaluate(self, one_hour_performance):
        rows = one_hour_performance.get("latest_scored") or []

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "HorizonOneHourLeaderboardEngine",
            "sample_count": len(rows),
            "symbol_leaderboard": self._rank_bucket(rows, "symbol"),
            "direction_leaderboard": self._rank_bucket(rows, "directional_bias"),
            "candidate_result_leaderboard": self._rank_bucket(rows, "candidate_result"),
            "status": "HORIZON_ONE_HOUR_LEADERBOARD_READY",
        }
