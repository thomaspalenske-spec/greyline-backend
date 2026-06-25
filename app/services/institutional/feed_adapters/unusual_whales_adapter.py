from .base_adapter import InstitutionalFeedAdapter
from datetime import datetime

class UnusualWhalesAdapter(InstitutionalFeedAdapter):
    provider_name = "UNUSUAL_WHALES"
    feed_type = "OPTIONS_FLOW"

    def evaluate(self, symbol):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "provider": self.provider_name,
            "feed_type": self.feed_type,
            "symbol": symbol.upper(),
            "available": False,
            "score": None,
            "direction": "UNKNOWN",
            "confidence": 0,
            "events": [],
            "status": "PROVIDER_NOT_CONNECTED",
        }
