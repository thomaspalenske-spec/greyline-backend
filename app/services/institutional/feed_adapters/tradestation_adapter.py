from .base_adapter import InstitutionalFeedAdapter
from datetime import datetime

class TradeStationInstitutionalAdapter(InstitutionalFeedAdapter):
    provider_name = "TRADESTATION"
    feed_type = "LEVEL2"

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
