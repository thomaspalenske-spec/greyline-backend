from datetime import datetime


class InstitutionalFlowEngine:
    def evaluate(self, context=None):
        context = context or {}

        buying = 0
        selling = 0
        evidence = []

        if context.get("symbols_scored", 0) > 0:
            evidence.append("OPPORTUNITY_UNIVERSE_ACTIVE")

        if context.get("top_candidate"):
            buying += 20
            evidence.append("TOP_CANDIDATE_PRESENT")

        if context.get("risk_state") == "NORMAL":
            buying += 15
            evidence.append("RISK_STATE_NORMAL")

        symmetry = context.get("symmetry", {})
        bullish_execute = symmetry.get("bullish_execute", 0)
        bearish_execute = symmetry.get("bearish_execute", 0)

        if bullish_execute > bearish_execute:
            buying += 25
            evidence.append("BULLISH_EXECUTE_IMBALANCE")

        if bearish_execute > bullish_execute:
            selling += 25
            evidence.append("BEARISH_EXECUTE_IMBALANCE")

        if symmetry.get("opportunity_bias") == "BULLISH_BIAS_DETECTED":
            buying += 20
            evidence.append("BULLISH_OPPORTUNITY_BIAS")

        if symmetry.get("opportunity_bias") == "BEARISH_BIAS_DETECTED":
            selling += 20
            evidence.append("BEARISH_OPPORTUNITY_BIAS")

        buying = min(buying, 100)
        selling = min(selling, 100)

        if buying > selling:
            net_flow = "BUYING_INFERRED"
        elif selling > buying:
            net_flow = "SELLING_INFERRED"
        else:
            net_flow = "NEUTRAL_INFERRED"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "InstitutionalFlowEngine",
            "institutional_buying": buying,
            "institutional_selling": selling,
            "net_flow": net_flow,
            "flow_source": "INFERRED_ONLY_DIRECT_FEEDS_NOT_CONNECTED",
            "direct_flow_feeds_connected": False,
            "evidence": evidence,
            "status": "INSTITUTIONAL_FLOW_EVALUATED",
        }
