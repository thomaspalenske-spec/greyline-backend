from datetime import datetime


class InstitutionalFlowProvider:
    """
    Adapter skeleton for future direct institutional feeds.
    Current status: no direct vendor feed connected.
    """

    def evaluate(self, symbol=None):
        symbol = (symbol or "").upper().strip()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "InstitutionalFlowProvider",
            "symbol": symbol,
            "direct_feed_connected": False,
            "feeds": {
                "options_flow": None,
                "dark_pool": None,
                "dealer_gamma": None,
                "order_flow": None,
                "vwap": None,
            },
            "missing_feeds": [
                "options_flow",
                "dark_pool",
                "dealer_gamma",
                "order_flow",
                "vwap",
            ],
            "status": "INSTITUTIONAL_FLOW_PROVIDER_NO_DIRECT_FEEDS",
        }
