from datetime import datetime

from app.services.equity_institutional_flow_engine import EquityInstitutionalFlowEngine


class InstitutionalFlowEngine:
    def evaluate_symbol(self, symbol):
        """
        Per-symbol institutional flow in the {institutional_flow_score,
        institutional_flow_state} shape consumed by the accumulation / distribution /
        summary dashboards. This class's own evaluate() is universe-level (inferred from
        the opportunity set), not per-symbol, so the per-symbol read is delegated to
        EquityInstitutionalFlowEngine (the real inferred equity proxy) and adapted here.
        """
        equity = EquityInstitutionalFlowEngine().evaluate_symbol(symbol)

        # net_institutional_flow_score is inflow-minus-outflow in [-100, 100]; map it to a
        # 0-100 buying-strength score (50 = neutral) as the consuming engines expect.
        net = equity.get("net_institutional_flow_score", 0) or 0
        flow_score = max(0, min(100, round(50 + net / 2)))
        direction = equity.get("institutional_flow_direction", "UNKNOWN")
        state = {
            "INFLOW": "INSTITUTIONAL_INFLOW",
            "OUTFLOW": "INSTITUTIONAL_OUTFLOW",
            "NEUTRAL": "NEUTRAL_FLOW",
        }.get(direction, "FLOW_UNKNOWN")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol.upper().strip(),
            "institutional_flow_score": flow_score,
            "institutional_flow_state": state,
            "institutional_flow_direction": direction,
            "institutional_flow_confidence": equity.get("institutional_flow_confidence", 0),
            "net_institutional_flow_score": net,
            "flow_source": equity.get("flow_source", "INFERRED_EQUITY_PROXY"),
            "direct_flow_feeds_connected": equity.get("direct_flow_feeds_connected", False),
            "status": "INSTITUTIONAL_FLOW_SYMBOL_READY",
        }

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
