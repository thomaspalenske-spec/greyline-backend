from datetime import datetime
from pathlib import Path
import csv


class HistoricalCsvImportEngine:
    """
    Normalizes downloaded historical OHLCV CSV files into GreyLine format.

    Output:
      app/data/historical/{SYMBOL}_daily.csv

    Required normalized columns:
      date,open,high,low,close,volume
    """

    _out_dir = Path("app/data/historical")

    def import_csv(self, symbol, input_path):
        symbol = (symbol or "").upper().strip()
        src = Path(input_path)
        if not src.exists():
            return {
                "status": "HISTORICAL_CSV_IMPORT_FILE_NOT_FOUND",
                "input_path": str(src),
            }

        self._out_dir.mkdir(parents=True, exist_ok=True)
        out = self._out_dir / f"{symbol}_daily.csv"

        rows = []
        with open(src, newline="") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                row = self._normalize_row(raw)
                if row:
                    rows.append(row)

        rows = sorted(rows, key=lambda r: r["date"])

        with open(out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerows(rows)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "HistoricalCsvImportEngine",
            "symbol": symbol,
            "input_path": str(src),
            "output_path": str(out),
            "rows_imported": len(rows),
            "first_date": rows[0]["date"] if rows else None,
            "last_date": rows[-1]["date"] if rows else None,
            "status": "HISTORICAL_CSV_IMPORT_READY",
        }

    def _normalize_row(self, raw):
        lowered = {str(k).strip().lower(): v for k, v in (raw or {}).items()}

        date = lowered.get("date") or lowered.get("datetime") or lowered.get("time")
        open_ = lowered.get("open")
        high = lowered.get("high")
        low = lowered.get("low")
        close = lowered.get("close") or lowered.get("adj close") or lowered.get("adj_close")
        volume = lowered.get("volume")

        if not date or open_ in [None, ""] or close in [None, ""]:
            return None

        return {
            "date": str(date)[:10],
            "open": self._num(open_),
            "high": self._num(high),
            "low": self._num(low),
            "close": self._num(close),
            "volume": self._num(volume),
        }

    @staticmethod
    def _num(value):
        try:
            return float(str(value).replace(",", "")) if value not in [None, ""] else None
        except Exception:
            return None
