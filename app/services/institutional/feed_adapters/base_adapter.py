from datetime import datetime


class InstitutionalFeedAdapter:
    provider_name = "BASE"
    feed_type = "UNKNOWN"

    def available(self):
        return False

    def evaluate(self, symbol):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "provider": self.provider_name,
            "feed_type": self.feed_type,
            "symbol": (symbol or "").upper().strip(),
            "available": self.available(),
            "score": None,
            "direction": "UNKNOWN",
            "confidence": 0,
            "events": [],
            "status": "INSTITUTIONAL_FEED_ADAPTER_NOT_CONNECTED",
        }
