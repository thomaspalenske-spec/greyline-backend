from datetime import datetime
from pathlib import Path
import csv


class HistoricalMarketDataProvider:
    """
    Historical OHLCV provider for walk-forward simulation.

    Looks for:
      app/data/historical/{SYMBOL}_daily.csv

    Expected CSV columns:
      date,open,high,low,close,volume

    If no file or no matching row exists, returns placeholder no-lookahead data.
    """

    _base_path = Path("app/data/historical")

    def get_snapshot(self, symbol, timestamp):
        symbol = (symbol or "").upper().strip()

        if isinstance(timestamp, datetime):
            dt = timestamp
        else:
            dt = datetime.fromisoformat(str(timestamp))

        row = self._load_daily_row(symbol, dt.date().isoformat())

        if row:
            return {
                "timestamp": dt.isoformat(),
                "symbol": symbol,
                "open": self._num(row.get("open")),
                "high": self._num(row.get("high")),
                "low": self._num(row.get("low")),
                "close": self._num(row.get("close")),
                "volume": self._num(row.get("volume")),
                "options_chain": None,
                "volatility": None,
                "source": "CSV_DAILY_NO_LOOKAHEAD",
                "future_visible": False,
                "status": "HISTORICAL_MARKET_DATA_READY",
            }

        return {
            "timestamp": dt.isoformat(),
            "symbol": symbol,
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

    def _load_daily_row(self, symbol, date_string):
        path = self._base_path / f"{symbol}_daily.csv"
        if not path.exists():
            return None

        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("date") == date_string:
                    return row

        return None

    @staticmethod
    def _num(value):
        try:
            return float(value) if value not in [None, ""] else None
        except Exception:
            return None
