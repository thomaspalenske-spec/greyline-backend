from datetime import datetime

from app.services.forecast_feedback_engine import ForecastFeedbackEngine
from app.services.forecast_weight_advisor_engine import ForecastWeightAdvisorEngine
from app.services.forecast_trust_score_engine import ForecastTrustScoreEngine
from app.services.forecast_horizon_attribution_engine import ForecastHorizonAttributionEngine
from app.services.forecast_regime_attribution_engine import ForecastRegimeAttributionEngine
from app.services.forecast_meta_learning_engine import ForecastMetaLearningEngine


class ForecastReliabilityDashboardEngine:

    def dashboard(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastReliabilityDashboardEngine",
            "feedback": ForecastFeedbackEngine().evaluate(),
            "trust": ForecastTrustScoreEngine().evaluate(),
            "weight_advisor": ForecastWeightAdvisorEngine().advise(),
            "horizon_attribution": ForecastHorizonAttributionEngine().evaluate(),
            "regime_attribution": ForecastRegimeAttributionEngine().evaluate(),
            "meta_learning": ForecastMetaLearningEngine().evaluate(),
            "status": "FORECAST_RELIABILITY_DASHBOARD_READY",
        }
