from datetime import datetime

from app.services.forecast_trust_score_engine import ForecastTrustScoreEngine
from app.services.forecast_component_attribution_engine import ForecastComponentAttributionEngine
from app.services.forecast_regime_attribution_engine import ForecastRegimeAttributionEngine
from app.services.forecast_meta_learning_engine import ForecastMetaLearningEngine


class ForecastAutoTuningEngine:
    def evaluate(self):
        trust = ForecastTrustScoreEngine().evaluate()
        component = ForecastComponentAttributionEngine().evaluate()
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

            if best in field_to_weight:
                weights[field_to_weight[best]] = 1.10

            if worst in field_to_weight and worst != best:
                weights[field_to_weight[worst]] = 0.90

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
            "regime_attribution": regime,
            "meta_learning": meta,
            "status": "FORECAST_AUTO_TUNING_READY",
        }
