from datetime import datetime

from app.services.learning_analytics_engine import LearningAnalyticsEngine
from app.services.decision_feature_attribution_engine import DecisionFeatureAttributionEngine


class DecisionWeightRecommendationEngine:

    def recommend(self):
        analytics = LearningAnalyticsEngine().summarize()
        attribution = DecisionFeatureAttributionEngine().analyze()

        recommendations = []

        failure_counts = attribution.get("failure_factor_counts", {})
        success_counts = attribution.get("success_factor_counts", {})

        for factor, failures in failure_counts.items():

            successes = success_counts.get(factor, 0)

            if failures > successes:
                recommendation = "INCREASE_WEIGHT_OR_THRESHOLD"
                rationale = (
                    f"{factor} appears more frequently in unfavorable outcomes "
                    f"than favorable outcomes"
                )
            elif successes > failures:
                recommendation = "DECREASE_THRESHOLD_OR_INCREASE_TRUST"
                rationale = (
                    f"{factor} appears more frequently in favorable outcomes"
                )
            else:
                recommendation = "NO_CHANGE"
                rationale = (
                    f"{factor} currently has insufficient evidence for adjustment"
                )

            recommendations.append({
                "factor": factor,
                "failures": failures,
                "successes": successes,
                "recommendation": recommendation,
                "rationale": rationale,
                "human_approval_required": True,
            })

        recommendations = sorted(
            recommendations,
            key=lambda x: x["failures"],
            reverse=True
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_WEIGHT_RECOMMENDATIONS",
            "learning_events": analytics.get("total_learning_events"),
            "system_confidence_trend": analytics.get("system_confidence_trend"),
            "recommendations": recommendations,
            "automatic_weight_changes_enabled": False,
            "human_approval_required": True,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_WEIGHT_RECOMMENDATIONS_READY",
        }
