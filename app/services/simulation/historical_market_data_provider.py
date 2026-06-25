from datetime import datetime


class HistoricalMarketDataProvider:
    """
    Historical market data provider for walk-forward simulation.

    Current version:
    - no external data feed required
    - returns a no-lookahead placeholder bar
    - designed to later read CSV/API/historical bars
    """

    def get_snapshot(self, symbol, simulated_time):
        if isinstance(simulated_time, str):
            simulated_time = datetime.fromisoformat(simulated_time)

        return {
            "timestamp": simulated_time.isoformat(),
            "symbol": (symbol or "").upper().strip(),
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "volume": None,
            "source": "PLACEHOLDER_NO_LOOKAHEAD",
            "future_visible": False,
            "status": "HISTORICAL_MARKET_DATA_PLACEHOLDER_READY",
        }
