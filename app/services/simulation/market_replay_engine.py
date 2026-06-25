from datetime import datetime, timedelta

from app.services.simulation.historical_market_data_provider import HistoricalMarketDataProvider


class MarketReplayEngine:
    """
    Supplies historical market timestamps one step at a time.

    This engine never exposes information beyond the current replay time.
    """

    def __init__(self,
                 symbol="QQQ",
                 start_date="2024-01-01",
                 end_date="2024-12-31",
                 step_days=1):

        self.symbol = symbol.upper()
        self.current = datetime.fromisoformat(start_date)
        self.end = datetime.fromisoformat(end_date)
        self.step = timedelta(days=step_days)

    def has_next(self):
        return self.current <= self.end

    def next(self):
        if not self.has_next():
            return None

        market_data = HistoricalMarketDataProvider().get_snapshot(
            self.symbol,
            self.current.isoformat(),
        )

        snapshot = {
            "symbol": self.symbol,
            "timestamp": self.current.isoformat(),
            "market_data": market_data,
            "future_visible": False,
            "status": "MARKET_REPLAY_SNAPSHOT_READY",
        }

        self.current += self.step
        return snapshot
