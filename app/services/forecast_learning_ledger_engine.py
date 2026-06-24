import json
from datetime import datetime
from pathlib import Path

from app.services.forecast_feedback_engine import ForecastFeedbackEngine
from app.services.forecast_weight_advisor_engine import ForecastWeightAdvisorEngine
from app.services.forecast_horizon_attribution_engine import ForecastHorizonAttributionEngine
from app.services.forecast_regime_attribution_engine import ForecastRegimeAttributionEngine
from app.services.forecast_component_attribution_engine import ForecastComponentAttributionEngine
from app.services.forecast_deployment_governance_engine import ForecastDeploymentGovernanceEngine


class ForecastLearningLedgerEngine:
    def __init__(self):
        self.grade_path = Path("app/data/forecast_outcome_grades.jsonl")
        self.ledger_path = Path("app/data/forecast_learning_ledger.jsonl")

    def record(self):
        feedback = ForecastFeedbackEngine().evaluate()
        weight_advisor = ForecastWeightAdvisorEngine().advise()
        horizon = ForecastHorizonAttributionEngine().evaluate()
        regime = ForecastRegimeAttributionEngine().evaluate()
        component = ForecastComponentAttributionEngine().evaluate()
        governance = ForecastDeploymentGovernanceEngine().evaluate()

        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastLearningLedgerEngine",
            "feedback": feedback,
            "weight_advisor": weight_advisor,
            "horizon_attribution": horizon,
            "regime_attribution": regime,
            "component_attribution": component,
            "deployment_governance": governance,
            "status": "FORECAST_LEARNING_LEDGER_RECORDED",
        }

        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

        with self.ledger_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

        return entry
