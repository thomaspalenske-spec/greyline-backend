
from datetime import datetime

class HistoricalMarketDataProvider:
    """
    Placeholder provider.

    Next implementation will read historical OHLCV bars from disk or an API.
    This interface is intentionally production-compatible.
    """

    def get_snapshot(self, symbol, timestamp):

        return {
            "timestamp": timestamp,
            "symbol": symbol.upper(),
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "volume": None,
            "options_chain": None,
            "volatility": None,
            "source": "PLACEHOLDER_NO_LOOKAHEAD",
            "future_visible": False,
            "status": "HISTORICAL_MARKET_DATA_PROVIDER_READY",
        }
