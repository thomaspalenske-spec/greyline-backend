from datetime import datetime

from app.services.relative_strength_engine import RelativeStrengthEngine
from app.services.volume_expansion_engine import VolumeExpansionEngine


class InstitutionalFlowEngine:

    def evaluate_symbol(self, symbol, benchmark="SPY"):
        symbol = symbol.upper().strip()

        relative_strength = RelativeStrengthEngine().compare_to_benchmark(symbol, benchmark)
        volume = VolumeExpansionEngine().calculate_volume_expansion(symbol)

        rs_score = relative_strength.get("relative_strength_score", 50)
        volume_score = volume.get("volume_score", 50)

        flow_score = round(
            (rs_score * 0.55) + (volume_score * 0.45),
            2
        )

        if flow_score >= 85:
            flow_state = "INSTITUTIONAL_INFLOW_CONFIRMED"
        elif flow_score >= 70:
            flow_state = "INSTITUTIONAL_INFLOW_WATCH"
        elif flow_score >= 50:
            flow_state = "NEUTRAL_FLOW"
        else:
            flow_state = "INSTITUTIONAL_OUTFLOW_RISK"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "benchmark": benchmark,
            "relative_strength_score": rs_score,
            "volume_score": volume_score,
            "institutional_flow_score": flow_score,
            "institutional_flow_state": flow_state,
            "execution_enabled": False,
            "status": "INSTITUTIONAL_FLOW_READY"
        }
