from datetime import datetime

from app.services.institutional.institutional_feed_aggregator import InstitutionalFeedAggregator


class InstitutionalFlowProvider:
    """
    Provider layer for direct institutional feeds.

    Current mode:
    - Uses InstitutionalFeedAggregator.
    - Synthetic adapter is active.
    - Direct vendor feeds are not yet connected.
    """

    def evaluate(self, symbol=None):
        symbol = (symbol or "").upper().strip()
        aggregate = InstitutionalFeedAggregator().evaluate(symbol)

        direct_connected = aggregate.get("direct_feed_connected") is True

        feeds = {
            "options_flow": None,
            "dark_pool": None,
            "dealer_gamma": None,
            "order_flow": None,
            "vwap": None,
        }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "InstitutionalFlowProvider",
            "symbol": symbol,
            "direct_feed_connected": direct_connected,
            "aggregate": aggregate,
            "feeds": feeds,
            "missing_feeds": [
                "options_flow",
                "dark_pool",
                "dealer_gamma",
                "order_flow",
                "vwap",
            ],
            "status": "INSTITUTIONAL_FLOW_PROVIDER_READY",
        }
