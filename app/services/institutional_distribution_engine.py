from datetime import datetime

from app.services.institutional_flow_engine import InstitutionalFlowEngine
from app.services.historical_momentum_engine import HistoricalMomentumEngine
from app.services.volume_expansion_engine import VolumeExpansionEngine


class InstitutionalDistributionEngine:

    def evaluate_symbol(self, symbol):
        symbol = symbol.upper().strip()

        flow = InstitutionalFlowEngine().evaluate_symbol(symbol)
        momentum = HistoricalMomentumEngine().calculate_momentum(symbol)
        volume = VolumeExpansionEngine().calculate_volume_expansion(symbol)

        flow_score = flow.get("institutional_flow_score", 50)
        momentum_score = momentum.get("momentum_score", 50)
        volume_score = volume.get("volume_score", 50)

        distribution_risk_score = round(
            ((100 - flow_score) * 0.45) +
            ((100 - momentum_score) * 0.35) +
            (volume_score * 0.20),
            2
        )

        if distribution_risk_score >= 75:
            state = "DISTRIBUTION_CONFIRMED"
        elif distribution_risk_score >= 60:
            state = "DISTRIBUTION_WATCH"
        elif distribution_risk_score >= 45:
            state = "NEUTRAL"
        else:
            state = "LOW_DISTRIBUTION_RISK"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "flow_score": flow_score,
            "momentum_score": momentum_score,
            "volume_score": volume_score,
            "distribution_risk_score": distribution_risk_score,
            "distribution_state": state,
            "execution_enabled": False,
            "status": "INSTITUTIONAL_DISTRIBUTION_READY"
        }
