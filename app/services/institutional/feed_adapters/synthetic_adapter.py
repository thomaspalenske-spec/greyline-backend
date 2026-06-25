from datetime import datetime

from app.services.institutional.feed_adapters.base_adapter import InstitutionalFeedAdapter


class SyntheticInstitutionalFeedAdapter(InstitutionalFeedAdapter):
    provider_name = "GREYLINE_SYNTHETIC"
    feed_type = "SYNTHETIC_INFERENCE"

    def available(self):
        return True

    def evaluate(self, symbol, candidate=None):
        candidate = candidate or {}

        liquidity = self._num(candidate.get("liquidity_score"))
        adjusted = self._num(candidate.get("adjusted_score") or candidate.get("score"))
        reliability = self._num(candidate.get("signal_reliability_score"))
        confidence = self._num(candidate.get("direction_confidence"))
        setup = self._num(candidate.get("setup_score"))

        score = round(min(100, max(0,
            liquidity * 0.25 +
            adjusted * 0.30 +
            reliability * 0.20 +
            confidence * 0.15 +
            setup * 0.10
        )), 2)

        option_type = (candidate.get("option_type") or "").upper()
        bias = (candidate.get("directional_bias") or "").upper()

        if option_type == "CALL" or "BULL" in bias:
            direction = "BULLISH"
        elif option_type == "PUT" or "BEAR" in bias:
            direction = "BEARISH"
        else:
            direction = "UNKNOWN"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "provider": self.provider_name,
            "feed_type": self.feed_type,
            "symbol": (symbol or "").upper().strip(),
            "available": True,
            "score": score,
            "direction": direction,
            "confidence": round(min(100, max(0, reliability * 0.55 + confidence * 0.45)), 2),
            "events": [],
            "status": "SYNTHETIC_INSTITUTIONAL_FEED_READY",
        }

    @staticmethod
    def _num(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0
