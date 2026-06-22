from datetime import datetime


class InstitutionalPremiumFlowEngine:
    """
    Institutional premium flow placeholder engine.

    Current mode:
    - No direct unusual-options feed connected yet.
    - Uses available GreyLine directional fields as inferred premium-flow proxy.
    - Designed so a real flow provider can be wired in later without changing downstream consumers.
    """

    def evaluate(self, candidate=None):
        candidate = candidate or {}

        symbol = candidate.get("symbol")
        option_type = candidate.get("option_type")
        directional_bias = candidate.get("directional_bias")

        bullish_score = float(candidate.get("bullish_score") or 0)
        bearish_score = float(candidate.get("bearish_score") or 0)
        confidence = float(candidate.get("direction_confidence") or 0)
        liquidity = float(candidate.get("liquidity_score") or 0)
        setup = float(candidate.get("setup_score") or 0)

        call_premium_flow = 0
        put_premium_flow = 0

        if option_type == "CALL" or directional_bias == "BULLISH":
            call_premium_flow = round((bullish_score * 10000) + (confidence * 5000) + (liquidity * 2500) + (setup * 2500), 2)

        if option_type == "PUT" or directional_bias == "BEARISH":
            put_premium_flow = round((bearish_score * 10000) + (confidence * 5000) + (liquidity * 2500) + (setup * 2500), 2)

        net_premium_flow = round(call_premium_flow - put_premium_flow, 2)

        if net_premium_flow > 250000:
            institutional_bias = "BULLISH_PREMIUM_FLOW_INFERRED"
        elif net_premium_flow < -250000:
            institutional_bias = "BEARISH_PREMIUM_FLOW_INFERRED"
        else:
            institutional_bias = "NEUTRAL_PREMIUM_FLOW_INFERRED"

        flow_strength = round(abs(net_premium_flow) / 10000, 2)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "InstitutionalPremiumFlowEngine",
            "symbol": symbol,
            "option_type": option_type,
            "directional_bias": directional_bias,
            "call_premium_flow": call_premium_flow,
            "put_premium_flow": put_premium_flow,
            "net_premium_flow": net_premium_flow,
            "institutional_bias": institutional_bias,
            "flow_strength": flow_strength,
            "direct_premium_flow_feed_connected": False,
            "flow_source": "INFERRED_PROXY_NO_DIRECT_OPTIONS_FLOW_FEED",
            "status": "INSTITUTIONAL_PREMIUM_FLOW_READY",
        }
