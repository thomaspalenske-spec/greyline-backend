from datetime import datetime


class ComponentWeightOptimizationEngine:
    BASE_WEIGHTS = {
        "regime": 20,
        "risk_state": 20,
        "breadth": 15,
        "setup": 20,
        "asymmetry": 15,
        "volatility": 10,
    }

    def _best_bucket_return(self, component_learning, key):
        rows = component_learning.get(key) or []
        if not rows:
            return 0, 0, "NO_DATA"

        best = rows[0]
        return (
            float(best.get("average_directional_return_pct") or 0),
            int(best.get("samples") or 0),
            best.get("bucket") or "UNKNOWN",
        )

    def _recommend_adjustment(self, avg_return, samples):
        if samples < 25:
            return 0, "INSUFFICIENT_SAMPLE_SIZE"

        if avg_return >= 0.15:
            return 3, "INCREASE_WEIGHT"
        if avg_return >= 0.05:
            return 1, "SLIGHT_INCREASE_WEIGHT"
        if avg_return <= -0.15:
            return -3, "DECREASE_WEIGHT"
        if avg_return <= -0.05:
            return -1, "SLIGHT_DECREASE_WEIGHT"

        return 0, "HOLD_WEIGHT"

    def evaluate(self, component_learning):
        component_map = {
            "regime": "regime_score_leaderboard",
            "risk_state": "risk_state_score_leaderboard",
            "breadth": "breadth_score_leaderboard",
            "setup": "setup_score_leaderboard",
            "asymmetry": "asymmetry_score_leaderboard",
            "volatility": "volatility_score_leaderboard",
        }

        recommendations = []
        proposed = dict(self.BASE_WEIGHTS)

        for component, key in component_map.items():
            avg_return, samples, bucket = self._best_bucket_return(component_learning, key)
            adjustment, action = self._recommend_adjustment(avg_return, samples)

            proposed[component] = max(0, proposed[component] + adjustment)

            recommendations.append({
                "component": component,
                "best_bucket": bucket,
                "samples": samples,
                "average_directional_return_pct": avg_return,
                "recommended_action": action,
                "weight_adjustment_pct": adjustment,
            })

        total = sum(proposed.values()) or 1
        normalized = {
            key: round((value / total) * 100, 2)
            for key, value in proposed.items()
        }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ComponentWeightOptimizationEngine",
            "mode": "ADVISORY_ONLY",
            "base_weights": self.BASE_WEIGHTS,
            "raw_proposed_weights": proposed,
            "normalized_proposed_weights": normalized,
            "recommendations": recommendations,
            "auto_apply_enabled": False,
            "status": "COMPONENT_WEIGHT_OPTIMIZATION_READY",
        }
