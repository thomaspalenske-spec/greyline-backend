from datetime import datetime

from app.services.institutional_flow_summary_engine import InstitutionalFlowSummaryEngine


class LeadershipRotationEngine:

    def evaluate_leaders(self, symbols):
        leaders = []

        for symbol in symbols:
            summary = InstitutionalFlowSummaryEngine().summarize_symbol(symbol)

            leaders.append({
                "symbol": symbol.upper(),
                "flow_score": summary.get("institutional_flow_score", 0),
                "accumulation_score": summary.get("accumulation_score", 0),
                "distribution_risk_score": summary.get("distribution_risk_score", 0)
            })

        leaders.sort(
            key=lambda x: x["flow_score"],
            reverse=True
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "leader_count": len(leaders),
            "leaders": leaders,
            "top_leader": leaders[0]["symbol"] if leaders else None,
            "execution_enabled": False,
            "status": "LEADERSHIP_ROTATION_READY"
        }
