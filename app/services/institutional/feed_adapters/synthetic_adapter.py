from datetime import datetime

from app.services.institutional.feed_adapters.base_adapter import InstitutionalFeedAdapter


class SyntheticInstitutionalFeedAdapter(InstitutionalFeedAdapter):
    provider_name = "GREYLINE_SYNTHETIC"
    feed_type = "SYNTHETIC_INFERENCE"

    def available(self):
        return True

    def evaluate(self, symbol):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "provider": self.provider_name,
            "feed_type": self.feed_type,
            "symbol": (symbol or "").upper().strip(),
            "available": True,
            "score": None,
            "direction": "UNKNOWN",
            "confidence": 0,
            "events": [],
            "status": "SYNTHETIC_INSTITUTIONAL_FEED_READY",
        }
