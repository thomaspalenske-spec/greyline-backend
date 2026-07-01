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
    _row_cache = {}
    _date_cache = {}


    def available_dates(self, symbol, start_date=None, end_date=None):
        symbol = (symbol or "").upper().strip()
        self._load_symbol(symbol)

        start = str(start_date)[:10] if start_date else None
        end = str(end_date)[:10] if end_date else None

        dates = self._date_cache.get(symbol, [])
        return [
            d for d in dates
            if (not start or d >= start) and (not end or d <= end)
        ]

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
                "open": self._num(float(row.get("open") or 0)),
                "high": self._num(float(row.get("high") or 0)),
                "low": self._num(float(row.get("low") or 0)),
                "close": self._num(float(row.get("close") or 0)),
                "volume": self._num(float(row.get("volume") or 0)),
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


    def get_history(self, symbol, timestamp, lookback=30):
        """
        Return historical daily rows up to and including timestamp.
        No future rows are visible.
        """
        symbol = (symbol or "").upper().strip()

        if isinstance(timestamp, datetime):
            dt = timestamp
        else:
            dt = datetime.fromisoformat(str(timestamp))

        self._load_symbol(symbol)
        cutoff = dt.date().isoformat()
        dates = [d for d in self._date_cache.get(symbol, []) if d <= cutoff]
        dates = dates[-int(lookback):]

        history = []
        for d in dates:
            row = self._row_cache.get(symbol, {}).get(d) or {}
            history.append({
                "date": d,
                "open": self._num(float(row.get("open") or 0)),
                "high": self._num(float(row.get("high") or 0)),
                "low": self._num(float(row.get("low") or 0)),
                "close": self._num(float(row.get("close") or 0)),
                "volume": self._num(float(row.get("volume") or 0)),
            })

        return history

    def _load_symbol(self, symbol):
        symbol = (symbol or "").upper().strip()
        if symbol in self._row_cache:
            return

        path = self._base_path / f"{symbol}_daily.csv"
        rows = {}
        dates = []

        if path.exists():
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    d = row.get("date")
                    if not d:
                        continue
                    rows[d] = row
                    dates.append(d)

        self._row_cache[symbol] = rows
        self._date_cache[symbol] = dates

    def _load_daily_row(self, symbol, date_string):
        symbol = (symbol or "").upper().strip()
        self._load_symbol(symbol)
        return self._row_cache.get(symbol, {}).get(date_string)

    @staticmethod
    def _num(value):
        try:
            return float(value) if value not in [None, ""] else None
        except Exception:
            return None
