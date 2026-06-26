from datetime import datetime, timedelta

from app.services.simulation.historical_market_data_provider import HistoricalMarketDataProvider


class MarketReplayEngine:
    """
    Supplies historical market timestamps one step at a time.

    Default behavior now walks actual CSV trading days when available.
    This prevents weekend/holiday placeholder decisions while preserving
    no-lookahead behavior.
    """

    def __init__(self,
                 symbol="QQQ",
                 start_date="2024-01-01",
                 end_date="2024-12-31",
                 step_days=1,
                 trading_days_only=True):

        self.symbol = symbol.upper()
        self.current = datetime.fromisoformat(start_date)
        self.end = datetime.fromisoformat(end_date)
        self.step = timedelta(days=step_days)
        self.trading_days_only = trading_days_only
        self.provider = HistoricalMarketDataProvider()

        self._dates = []
        self._index = 0

        if trading_days_only:
            self._dates = self.provider.available_dates(
                self.symbol,
                self.current.date().isoformat(),
                self.end.date().isoformat(),
            )

    def has_next(self):
        if self.trading_days_only:
            return self._index < len(self._dates)
        return self.current <= self.end

    def next(self):
        if not self.has_next():
            return None

        if self.trading_days_only:
            replay_time = datetime.fromisoformat(self._dates[self._index])
            self._index += 1
        else:
            replay_time = self.current
            self.current += self.step

        market_data = self.provider.get_snapshot(
            self.symbol,
            replay_time.isoformat(),
        )

        return {
            "symbol": self.symbol,
            "timestamp": replay_time.isoformat(),
            "market_data": market_data,
            "future_visible": False,
            "status": "MARKET_REPLAY_SNAPSHOT_READY",
        }
