from datetime import datetime
from app.services.institutional_premium_flow_engine import InstitutionalPremiumFlowEngine


class DirectionalFlowConfirmationEngine:
    def evaluate(self, candidate=None):
        candidate = candidate or {}

        directional_bias = candidate.get("directional_bias")
        option_type = candidate.get("option_type")

        bullish_score = float(candidate.get("bullish_score") or 0)
        bearish_score = float(candidate.get("bearish_score") or 0)
        confidence = float(candidate.get("direction_confidence") or 0)
        liquidity = float(candidate.get("liquidity_score") or 0)
        setup = float(candidate.get("setup_score") or 0)

        if option_type == "CALL" or directional_bias == "BULLISH":
            flow_side = "BUYING_INFERRED"
            aligned = bullish_score > bearish_score
            flow_strength = round((bullish_score * 0.45) + (confidence * 0.25) + (liquidity * 0.15) + (setup * 0.15), 2)
        elif option_type == "PUT" or directional_bias == "BEARISH":
            flow_side = "SELLING_INFERRED"
            aligned = bearish_score > bullish_score
            flow_strength = round((bearish_score * 0.45) + (confidence * 0.25) + (liquidity * 0.15) + (setup * 0.15), 2)
        else:
            flow_side = "UNKNOWN"
            aligned = False
            flow_strength = 0

        premium_flow = InstitutionalPremiumFlowEngine().evaluate(candidate)

        if flow_strength >= 80 and aligned:
            confirmation = "STRONG_FLOW_CONFIRMATION"
        elif flow_strength >= 65 and aligned:
            confirmation = "MODERATE_FLOW_CONFIRMATION"
        elif aligned:
            confirmation = "WEAK_FLOW_CONFIRMATION"
        else:
            confirmation = "NO_FLOW_CONFIRMATION"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "DirectionalFlowConfirmationEngine",
            "symbol": candidate.get("symbol"),
            "directional_bias": directional_bias,
            "option_type": option_type,
            "flow_side": flow_side,
            "flow_aligned": aligned,
            "flow_strength": flow_strength,
            "confirmation": confirmation,
            "premium_flow": premium_flow,
            "direct_flow_feeds_connected": False,
            "flow_source": "INFERRED_FROM_DIRECTIONAL_SCORE_LIQUIDITY_SETUP_CONFIDENCE",
            "status": "DIRECTIONAL_FLOW_CONFIRMATION_READY",
        }
