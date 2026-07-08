from datetime import datetime

from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider


class InstitutionalPremiumFlowEngine:
    """
    Institutional premium flow engine.

    Priority:
    1. Direct Unusual Whales options flow when available.
    2. Existing inferred proxy fallback when direct flow is unavailable.
    """

    def __init__(self):
        try:
            self.uw = UnusualWhalesProvider()
        except Exception:
            self.uw = None

    def _direct_unusual_whales_flow(self, symbol):
        if not self.uw or not symbol:
            return None

        flow = self.uw.recent_flow(symbol)

        if not isinstance(flow, list) or not flow:
            return None

        call_premium_flow = 0.0
        put_premium_flow = 0.0

        for trade in flow:
            tags = [str(t).lower() for t in (trade.get("tags") or [])]
            option_type = str(trade.get("option_type") or "").lower()

            try:
                premium = float(trade.get("premium") or 0)
            except Exception:
                premium = 0.0

            if premium <= 0:
                continue

            if "bullish" in tags or option_type == "call":
                call_premium_flow += premium
            elif "bearish" in tags or option_type == "put":
                put_premium_flow += premium

        call_premium_flow = round(call_premium_flow, 2)
        put_premium_flow = round(put_premium_flow, 2)
        net_premium_flow = round(call_premium_flow - put_premium_flow, 2)

        if net_premium_flow > 250000:
            institutional_bias = "BULLISH_PREMIUM_FLOW_DIRECT"
        elif net_premium_flow < -250000:
            institutional_bias = "BEARISH_PREMIUM_FLOW_DIRECT"
        else:
            institutional_bias = "NEUTRAL_PREMIUM_FLOW_DIRECT"

        return {
            "call_premium_flow": call_premium_flow,
            "put_premium_flow": put_premium_flow,
            "net_premium_flow": net_premium_flow,
            "institutional_bias": institutional_bias,
            "flow_strength": round(abs(net_premium_flow) / 10000, 2),
            "direct_premium_flow_feed_connected": True,
            "flow_source": "UNUSUAL_WHALES_DIRECT_OPTIONS_FLOW",
        }

    def evaluate(self, candidate=None):
        candidate = candidate or {}

        symbol = candidate.get("symbol")
        option_type = candidate.get("option_type")
        directional_bias = candidate.get("directional_bias")

        try:
            direct = self._direct_unusual_whales_flow(symbol)
        except Exception:
            direct = None

        if direct:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": "GreyLine",
                "engine": "InstitutionalPremiumFlowEngine",
                "symbol": symbol,
                "option_type": option_type,
                "directional_bias": directional_bias,
                **direct,
                "status": "INSTITUTIONAL_PREMIUM_FLOW_READY",
            }

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
            "flow_strength": round(abs(net_premium_flow) / 10000, 2),
            "direct_premium_flow_feed_connected": False,
            "flow_source": "INFERRED_PROXY_NO_DIRECT_OPTIONS_FLOW_FEED",
            "status": "INSTITUTIONAL_PREMIUM_FLOW_READY",
        }
