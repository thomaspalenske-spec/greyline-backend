from datetime import datetime

from app.services.forecast_trust_score_engine import ForecastTrustScoreEngine
from app.services.forecast_component_attribution_engine import ForecastComponentAttributionEngine
from app.services.forecast_regime_attribution_engine import ForecastRegimeAttributionEngine
from app.services.forecast_meta_learning_engine import ForecastMetaLearningEngine
from app.services.adaptive_weight_optimizer import AdaptiveWeightOptimizer
from app.services.forecast_component_correlation_engine import (
    ForecastComponentCorrelationEngine,
)
from app.services.forecast_walk_forward_validation_engine import (
    ForecastWalkForwardValidationEngine,
)


class ForecastAutoTuningEngine:
    def evaluate(self):
        trust = ForecastTrustScoreEngine().evaluate()
        component = ForecastComponentAttributionEngine().evaluate()

        AdaptiveWeightOptimizer().optimize(
            component.get("components", {})
        )

        regime = ForecastRegimeAttributionEngine().evaluate()
        meta = ForecastMetaLearningEngine().evaluate()

        confidence_level = trust.get("confidence_level")
        sample_size = int(trust.get("sample_size") or 0)

        weights = {
            "regime_weight": 1.00,
            "risk_state_weight": 1.00,
            "breadth_weight": 1.00,
            "setup_weight": 1.00,
            "asymmetry_weight": 1.00,
            "volatility_weight": 1.00,
        }

        learned = AdaptiveWeightOptimizer().load()
        correlation = (
            ForecastComponentCorrelationEngine()
            .evaluate()
        )

        walk_forward = (
            ForecastWalkForwardValidationEngine()
            .evaluate()
        )

        qualified_predictors = set(
            walk_forward.get(
                "qualified_predictors"
            )
            or []
        )

        field_map = {
            "regime_score": "regime_weight",
            "risk_state_score": "risk_state_weight",
            "breadth_score": "breadth_weight",
            "setup_score": "setup_weight",
            "asymmetry_score": "asymmetry_weight",
            "volatility_score": "volatility_weight",
        }

        walk_forward_decisions = []

        for factor, weight_name in field_map.items():
            learned_weight = float(
                (
                    learned.get(factor)
                    or {}
                ).get("weight", 1.0)
            )

            qualified = (
                factor in qualified_predictors
            )

            weights[weight_name] = (
                learned_weight
                if qualified
                else 1.0
            )

            walk_forward_decisions.append({
                "factor": factor,
                "weight_name": weight_name,
                "learned_weight": learned_weight,
                "applied_weight": weights[
                    weight_name
                ],
                "walk_forward_qualified": (
                    qualified
                ),
                "action": (
                    "APPLY_LEARNED_WEIGHT"
                    if qualified
                    else "HOLD_NEUTRAL_WEIGHT"
                ),
            })

        components = component.get("components") or {}

        redundant_pairs = [
            pair
            for pair in correlation.get(
                "redundant_pairs",
                [],
            )
            if (
                pair.get("left") in field_map
                and pair.get("right") in field_map
            )
        ]

        parent = {}

        def find(name):
            parent.setdefault(name, name)

            while parent[name] != name:
                parent[name] = parent[parent[name]]
                name = parent[name]

            return name

        def union(left, right):
            left_root = find(left)
            right_root = find(right)

            if left_root != right_root:
                parent[right_root] = left_root

        for pair in redundant_pairs:
            union(
                pair.get("left"),
                pair.get("right"),
            )

        clusters = {}

        for name in parent:
            clusters.setdefault(
                find(name),
                [],
            ).append(name)

        redundancy_decisions = []

        for members in clusters.values():
            if len(members) < 2:
                continue

            ranked_members = sorted(
                members,
                key=lambda name: (
                    float(
                        (
                            components.get(name) or {}
                        ).get(
                            "absolute_predictive_score_pct"
                        )
                        or 0.0
                    ),
                    float(
                        (
                            components.get(name) or {}
                        ).get(
                            "predictive_score_pct"
                        )
                        or 0.0
                    ),
                    int(
                        (
                            components.get(name) or {}
                        ).get("sample_size")
                        or 0
                    ),
                    name,
                ),
                reverse=True,
            )

            retained = ranked_members[0]
            suppressed = ranked_members[1:]

            for name in suppressed:
                weights[field_map[name]] = 1.0

            correlations = [
                pair
                for pair in redundant_pairs
                if (
                    pair.get("left") in members
                    and pair.get("right") in members
                )
            ]

            redundancy_decisions.append({
                "retained": retained,
                "suppressed": suppressed,
                "retained_predictive_score": float(
                    (
                        components.get(retained) or {}
                    ).get(
                        "absolute_predictive_score_pct"
                    )
                    or 0.0
                ),
                "maximum_absolute_correlation": max(
                    (
                        float(
                            pair.get(
                                "absolute_correlation"
                            )
                            or 0.0
                        )
                        for pair in correlations
                    ),
                    default=0.0,
                ),
                "cluster_members": sorted(members),
            })

        recommendation = "HOLD_WEIGHTS"
        reason = "INSUFFICIENT_MATURE_FORECAST_SAMPLE"

        if sample_size >= 10:
            components = component.get("components") or {}

            best = component.get("best_predictor")
            worst = component.get("worst_predictor")

            field_to_weight = {
                "regime_score": "regime_weight",
                "risk_state_score": "risk_state_weight",
                "breadth_score": "breadth_weight",
                "setup_score": "setup_weight",
                "asymmetry_score": "asymmetry_weight",
                "volatility_score": "volatility_weight",
            }

            actionable_components = [
                name
                for name, data in components.items()
                if data.get("actionable") is True
            ]

            if not actionable_components:
                if best in field_to_weight:
                    weights[field_to_weight[best]] = 1.02

                if worst in field_to_weight and worst != best:
                    weights[field_to_weight[worst]] = 0.98

            if confidence_level in ["HIGHLY_TRUSTED", "TRUSTED"]:
                recommendation = "APPLY_CONFIDENCE_WEIGHT_TUNING"
                reason = "FORECAST_TRUST_SUPPORTS_ADAPTIVE_TUNING"
            elif confidence_level == "DISTRUSTED":
                recommendation = "REDUCE_FORECAST_INFLUENCE"
                reason = "FORECAST_TRUST_WEAK"
                weights = {k: 0.90 for k in weights}
            else:
                recommendation = "HOLD_WEIGHTS"
                reason = "FORECAST_TRUST_NEUTRAL"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastAutoTuningEngine",
            "sample_size": sample_size,
            "confidence_level": confidence_level,
            "weights": weights,
            "recommendation": recommendation,
            "reason": reason,
            "trust_score": trust,
            "component_attribution": component,
            "component_correlation": correlation,
            "redundancy_decisions": (
                redundancy_decisions
            ),
            "walk_forward_validation": (
                walk_forward
            ),
            "walk_forward_decisions": (
                walk_forward_decisions
            ),
            "regime_attribution": regime,
            "meta_learning": meta,
            "status": "FORECAST_AUTO_TUNING_READY",
        }
