from .base_adapter import InstitutionalFeedAdapter
from datetime import datetime

class BlackBoxStocksAdapter(InstitutionalFeedAdapter):
    provider_name = "BLACKBOX_STOCKS"
    feed_type = "DARK_POOL"

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
