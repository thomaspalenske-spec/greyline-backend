from datetime import datetime

from app.services.institutional_flow_engine import InstitutionalFlowEngine
from app.services.historical_momentum_engine import HistoricalMomentumEngine


class InstitutionalAccumulationEngine:

    def evaluate_symbol(self, symbol):
        flow = InstitutionalFlowEngine().evaluate_symbol(symbol)
        momentum = HistoricalMomentumEngine().calculate_momentum(symbol)

        flow_score = flow.get("institutional_flow_score", 50)
        momentum_score = momentum.get("momentum_score", 50)

        accumulation_score = round(
            (flow_score * 0.60) +
            (momentum_score * 0.40),
            2
        )

        if accumulation_score >= 85:
            state = "ACCUMULATION_CONFIRMED"
        elif accumulation_score >= 70:
            state = "ACCUMULATION_WATCH"
        elif accumulation_score >= 50:
            state = "NEUTRAL"
        else:
            state = "DISTRIBUTION_RISK"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol.upper(),
            "flow_score": flow_score,
            "momentum_score": momentum_score,
            "accumulation_score": accumulation_score,
            "accumulation_state": state,
            "execution_enabled": False,
            "status": "INSTITUTIONAL_ACCUMULATION_READY"
        }
