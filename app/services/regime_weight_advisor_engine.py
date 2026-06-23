from datetime import datetime


class RegimeWeightAdvisorEngine:
    def evaluate(self, regime_learning):
        recommendations = []

        for row in regime_learning.get("regime_leaderboard", []):
            samples = row.get("samples", 0)
            avg = row.get("average_directional_return_pct", 0)

            if samples < 10:
                continue

            if avg > 0.10:
                action = "INCREASE_WEIGHT"
            elif avg < -0.10:
                action = "DECREASE_WEIGHT"
            else:
                action = "HOLD_WEIGHT"

            recommendations.append({
                "regime": row.get("regime"),
                "samples": samples,
                "average_directional_return_pct": avg,
                "recommended_action": action,
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "RegimeWeightAdvisorEngine",
            "recommendations": recommendations,
            "status": "REGIME_WEIGHT_ADVISOR_READY",
        }
