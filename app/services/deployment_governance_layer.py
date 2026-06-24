from datetime import datetime

from app.services.risk_state_scoring_engine import RiskStateScoringEngine
from app.services.regime_scoring_engine import RegimeScoringEngine
from app.services.volatility_scoring_engine import VolatilityScoringEngine
from app.services.forecast_influence_engine import ForecastInfluenceEngine
from app.services.portfolio_governor_engine import PortfolioGovernorEngine


class DeploymentGovernanceLayer:
    """
    Converts GreyLine from binary gate suppression into weighted deployment scoring.
    Hard safety gates remain external and non-negotiable.
    """

    WEIGHTS = {
        "trade_quality": 0.25,
        "risk_state": 0.20,
        "regime": 0.15,
        "institutional": 0.15,
        "volatility": 0.10,
        "portfolio": 0.10,
        "dppl": 0.05,
    }

    def score(self, inputs=None, symbol=None):
        inputs = inputs or {}

        default_scores = {
            "trade_quality": 75,
            "risk_state": 90,
            "regime": 70,
            "institutional": 65,
            "volatility": 70,
            "portfolio": 85,
            "dppl": 80,
        }

        live_context = {}

        if symbol:
            symbol = symbol.upper().strip()

            risk_result = RiskStateScoringEngine().score_symbol(symbol)
            regime_result = RegimeScoringEngine().score_symbol(symbol)
            volatility_result = VolatilityScoringEngine().score_symbol(symbol)

            inputs.setdefault("risk_state", risk_result.get("risk_state_score", default_scores["risk_state"]))
            inputs.setdefault("regime", regime_result.get("regime_score", default_scores["regime"]))
            inputs.setdefault("volatility", volatility_result.get("volatility_score", default_scores["volatility"]))

            live_context = {
                "symbol": symbol,
                "risk_state": risk_result,
                "regime": regime_result,
                "volatility": volatility_result,
            }

        scores = {**default_scores, **inputs}

        deployment_score = round(
            sum(scores[k] * self.WEIGHTS[k] for k in self.WEIGHTS), 2
        )

        state = self._state(deployment_score)
        base_allocation = self._allocation(deployment_score)

        forecast_influence = ForecastInfluenceEngine().evaluate(
            forecast_score=deployment_score,
            confidence=state,
        )

        influence_multiplier = float(
            forecast_influence.get("influence_multiplier") or 1.0
        )

        forecast_adjusted_allocation = min(
            100,
            max(0, round(base_allocation * influence_multiplier, 2))
        )

        portfolio_governor = PortfolioGovernorEngine().evaluate(
            deployment_score=deployment_score,
            candidate_symbol=symbol,
        )

        portfolio_max_deployment = float(
            portfolio_governor.get("max_deployment_pct") or 0
        )

        allocation = min(forecast_adjusted_allocation, portfolio_max_deployment)

        if not portfolio_governor.get("new_trade_allowed", False):
            state = "PORTFOLIO_BLOCKED"
            allocation = 0
        elif portfolio_governor.get("portfolio_decision") == "REDUCE" and state in ["EXECUTE", "EXECUTE_AGGRESSIVE"]:
            state = "EXECUTE_REDUCED_BY_PORTFOLIO"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "DeploymentGovernanceLayer",
            "deployment_score": deployment_score,
            "deployment_state": state,
            "recommended_position_size_pct": allocation,
            "base_recommended_position_size_pct": base_allocation,
            "forecast_adjusted_position_size_pct": forecast_adjusted_allocation,
            "portfolio_governor": portfolio_governor,
            "portfolio_decision": portfolio_governor.get("portfolio_decision"),
            "portfolio_warnings": portfolio_governor.get("warnings", []),
            "portfolio_blockers": portfolio_governor.get("blockers", []),
            "forecast_influence_multiplier": influence_multiplier,
            "forecast_influence": forecast_influence,
            "scores": scores,
            "weights": self.WEIGHTS,
            "symbol": symbol,
            "live_context": live_context,
            "hard_safety_gates_preserved": True,
            "status": "DEPLOYMENT_GOVERNANCE_READY",
        }

    def _state(self, score):
        if score >= 90:
            return "EXECUTE_AGGRESSIVE"
        if score >= 80:
            return "EXECUTE"
        if score >= 70:
            return "READY"
        if score >= 60:
            return "DEVELOPING"
        return "REJECT"

    def _allocation(self, score):
        if score >= 95:
            return 100
        if score >= 90:
            return 80
        if score >= 80:
            return 60
        if score >= 70:
            return 40
        if score >= 60:
            return 20
        return 0
