from datetime import datetime


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

    def score(self, inputs=None):
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

        scores = {**default_scores, **inputs}

        deployment_score = round(
            sum(scores[k] * self.WEIGHTS[k] for k in self.WEIGHTS), 2
        )

        state = self._state(deployment_score)
        allocation = self._allocation(deployment_score)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "DeploymentGovernanceLayer",
            "deployment_score": deployment_score,
            "deployment_state": state,
            "recommended_position_size_pct": allocation,
            "scores": scores,
            "weights": self.WEIGHTS,
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
