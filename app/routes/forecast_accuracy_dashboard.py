from fastapi import APIRouter
from app.services.forecast_accuracy_dashboard_engine import ForecastAccuracyDashboardEngine
from app.services.forecast_outcome_grader_engine import ForecastOutcomeGraderEngine
from app.services.forecast_feedback_engine import ForecastFeedbackEngine
from app.services.forecast_weight_advisor_engine import ForecastWeightAdvisorEngine
from app.services.forecast_trust_score_engine import ForecastTrustScoreEngine
from app.services.forecast_adaptive_threshold_engine import ForecastAdaptiveThresholdEngine
from app.services.forecast_horizon_attribution_engine import ForecastHorizonAttributionEngine
from app.services.forecast_regime_attribution_engine import ForecastRegimeAttributionEngine
from app.services.forecast_component_attribution_engine import ForecastComponentAttributionEngine
from app.services.forecast_deployment_governance_engine import ForecastDeploymentGovernanceEngine
from app.services.forecast_meta_learning_engine import ForecastMetaLearningEngine
from app.services.forecast_quality_gate_engine import ForecastQualityGateEngine
from app.services.forecast_auto_tuning_engine import ForecastAutoTuningEngine

router = APIRouter()


@router.get("/forecast-accuracy-dashboard")
def forecast_accuracy_dashboard():
    grader = ForecastOutcomeGraderEngine().grade_pending()
    dashboard = ForecastAccuracyDashboardEngine().dashboard()
    feedback = ForecastFeedbackEngine().evaluate()
    weight_advisor = ForecastWeightAdvisorEngine().advise()
    trust_score = ForecastTrustScoreEngine().evaluate()
    adaptive_threshold = ForecastAdaptiveThresholdEngine().evaluate()
    horizon_attribution = ForecastHorizonAttributionEngine().evaluate()
    regime_attribution = ForecastRegimeAttributionEngine().evaluate()
    component_attribution = ForecastComponentAttributionEngine().evaluate()
    deployment_governance = ForecastDeploymentGovernanceEngine().evaluate()
    meta_learning = ForecastMetaLearningEngine().evaluate()
    quality_gate = ForecastQualityGateEngine().evaluate()
    auto_tuning = ForecastAutoTuningEngine().evaluate()

    return {
        "system": "GreyLine",
        "route": "ForecastAccuracyDashboardRoute",
        "grader": grader,
        "dashboard": dashboard,
        "feedback": feedback,
        "weight_advisor": weight_advisor,
        "trust_score": trust_score,
        "adaptive_threshold": adaptive_threshold,
        "horizon_attribution": horizon_attribution,
        "regime_attribution": regime_attribution,
        "component_attribution": component_attribution,
        "deployment_governance": deployment_governance,
        "meta_learning": meta_learning,
        "quality_gate": quality_gate,
        "auto_tuning": auto_tuning,
        "status": "FORECAST_ACCURACY_DASHBOARD_ROUTE_READY",
    }
