import json
from datetime import datetime
from pathlib import Path

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class ForwardOutcomeCaptureEngine:
    def __init__(self):
        self.ledger_file = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")

    def _last_price(self, symbol):
        quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)
        quotes = (quote_result.get("response_json") or {}).get("Quotes") or []
        row = quotes[0] if quotes else {}

        try:
            price = float(row.get("Last") or 0)
        except Exception:
            price = 0.0

        return {
            "symbol": symbol,
            "price": price,
            "quote_status": quote_result.get("status"),
            "trade_time": row.get("TradeTime"),
            "is_delayed": bool((row.get("MarketFlags") or {}).get("IsDelayed")),
        }

    def capture(self, limit=25):
        if not self.ledger_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "records_checked": 0,
                "status": "NO_FORWARD_OUTCOME_LEDGER",
            }

        lines = self.ledger_file.read_text().splitlines()
        records = [json.loads(x) for x in lines[-limit:] if x.strip()]

        symbols = sorted(set(r.get("symbol") for r in records if r.get("symbol")))
        prices = {symbol: self._last_price(symbol) for symbol in symbols}

        outcomes = []
        for r in records:
            symbol = r.get("symbol")
            price = prices.get(symbol, {})
            current_price = price.get("price") or 0

            if current_price <= 0:
                outcome_state = "PRICE_UNAVAILABLE"
            else:
                outcome_state = "PRICE_CAPTURED"

            outcomes.append({
                "timestamp": datetime.utcnow().isoformat(),
                "candidate_timestamp": r.get("timestamp"),
                "symbol": symbol,
                "option_type": r.get("option_type"),
                "directional_bias": r.get("directional_bias"),
                "candidate_result": r.get("result"),
                "candidate_score": r.get("score"),
                "candidate_rank": r.get("rank"),
                "current_price": current_price,
                "quote_trade_time": price.get("trade_time"),
                "quote_is_delayed": price.get("is_delayed"),
                "outcome_state": outcome_state,
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ForwardOutcomeCaptureEngine",
            "records_checked": len(records),
            "symbols_checked": symbols,
            "outcomes": outcomes,
            "status": "FORWARD_OUTCOME_CAPTURE_READY",
        }
