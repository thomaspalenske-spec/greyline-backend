from datetime import datetime
import json
from pathlib import Path

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class ForecastOutcomeCaptureEngine:
    def __init__(self):
        self.outcome_path = Path("app/data/forecast_outcomes.jsonl")

    def _last_price(self, symbol):
        if not symbol:
            return {
                "price": None,
                "quote_status": "NO_SYMBOL",
                "trade_time": None,
            }

        quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)
        quotes = (quote_result.get("response_json") or {}).get("Quotes") or []
        row = quotes[0] if quotes else {}

        try:
            price = float(row.get("Last") or 0)
        except Exception:
            price = 0.0

        return {
            "price": price if price > 0 else None,
            "quote_status": quote_result.get("status"),
            "trade_time": row.get("TradeTime"),
        }

    def capture(self, forecast):
        symbol = forecast.get("symbol")
        price_info = self._last_price(symbol)

        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "forecast_id": forecast.get("forecast_id") or forecast.get("timestamp"),
            "symbol": symbol,
            "predicted_direction": forecast.get("directional_bias"),
            "predicted_score": forecast.get("composite_score") or forecast.get("score"),
            "snapshot_price": price_info.get("price"),
            "quote_status": price_info.get("quote_status"),
            "quote_trade_time": price_info.get("trade_time"),
            "forecast_timestamp": forecast.get("timestamp"),
            "status": "FORECAST_OUTCOME_CAPTURED_PENDING_MARKET_RESULT",
        }

        self.outcome_path.parent.mkdir(parents=True, exist_ok=True)

        with self.outcome_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

        return record
