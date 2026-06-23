from datetime import datetime


class ComponentLearningEngine:
    def _bucket_label(self, value):
        try:
            value = float(value)
        except Exception:
            return "UNKNOWN"

        if value >= 85:
            return "85_100_ELITE"
        if value >= 70:
            return "70_84_STRONG"
        if value >= 50:
            return "50_69_NEUTRAL"
        return "0_49_WEAK"

    def _leaderboard(self, rows, field):
        buckets = {}

        for row in rows or []:
            label = self._bucket_label(row.get(field))
            buckets.setdefault(label, []).append(row)

        output = []

        for label, items in buckets.items():
            wins = [x for x in items if x.get("prediction_correct")]
            avg_return = round(
                sum(float(x.get("directional_return_pct") or 0) for x in items) / len(items),
                4
            ) if items else 0

            output.append({
                "bucket": label,
                "samples": len(items),
                "wins": len(wins),
                "win_rate_pct": round((len(wins) / len(items)) * 100, 2) if items else 0,
                "average_directional_return_pct": avg_return,
            })

        return sorted(
            output,
            key=lambda x: x.get("average_directional_return_pct", 0),
            reverse=True,
        )

    def evaluate(self, one_hour_performance):
        rows = one_hour_performance.get("latest_scored") or []

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ComponentLearningEngine",
            "horizon": "ONE_HOUR",
            "sample_count": len(rows),
            "regime_score_leaderboard": self._leaderboard(rows, "regime_score"),
            "risk_state_score_leaderboard": self._leaderboard(rows, "risk_state_score"),
            "breadth_score_leaderboard": self._leaderboard(rows, "breadth_score"),
            "setup_score_leaderboard": self._leaderboard(rows, "setup_score_context"),
            "asymmetry_score_leaderboard": self._leaderboard(rows, "asymmetry_score"),
            "volatility_score_leaderboard": self._leaderboard(rows, "volatility_score"),
            "status": "COMPONENT_LEARNING_READY",
        }
