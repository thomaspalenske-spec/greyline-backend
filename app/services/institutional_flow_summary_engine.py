from datetime import datetime

from app.services.institutional_flow_engine import InstitutionalFlowEngine
from app.services.institutional_accumulation_engine import InstitutionalAccumulationEngine
from app.services.institutional_distribution_engine import InstitutionalDistributionEngine


class InstitutionalFlowSummaryEngine:

    def summarize_symbol(self, symbol):
        symbol = symbol.upper().strip()

        flow = InstitutionalFlowEngine().evaluate_symbol(symbol)
        accumulation = InstitutionalAccumulationEngine().evaluate_symbol(symbol)
        distribution = InstitutionalDistributionEngine().evaluate_symbol(symbol)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "institutional_flow_score": flow.get("institutional_flow_score"),
            "institutional_flow_state": flow.get("institutional_flow_state"),
            "accumulation_score": accumulation.get("accumulation_score"),
            "accumulation_state": accumulation.get("accumulation_state"),
            "distribution_risk_score": distribution.get("distribution_risk_score"),
            "distribution_state": distribution.get("distribution_state"),
            "execution_enabled": False,
            "status": "INSTITUTIONAL_FLOW_SUMMARY_READY"
        }
