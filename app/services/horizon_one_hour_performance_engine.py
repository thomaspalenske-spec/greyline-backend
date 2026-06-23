import json
from datetime import datetime
from pathlib import Path

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class HorizonOneHourPerformanceEngine:
    def __init__(self):
        self.file = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")

    def _parse_dt(self, value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    def _last_price(self, symbol):
        quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)
        quotes = (quote_result.get("response_json") or {}).get("Quotes") or []
        row = quotes[0] if quotes else {}

        try:
            return float(row.get("Last") or 0)
        except Exception:
            return 0.0

    def evaluate(self, limit=500):
        if not self.file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "record_count": 0,
                "status": "NO_HORIZON_DATA",
            }

        rows = [json.loads(x) for x in self.file.read_text().splitlines()[-limit:] if x.strip()]
        now = datetime.utcnow()

        prices = {}
        scored = []

        for r in rows:
            ts = self._parse_dt(r.get("timestamp"))
            if not ts:
                continue

            age_hours = round((now - ts).total_seconds() / 3600, 2)
            if age_hours < 1:
                continue

            symbol = r.get("symbol")
            snapshot = float(r.get("snapshot_price") or 0)
            if not symbol or snapshot <= 0:
                continue

            if symbol not in prices:
                prices[symbol] = self._last_price(symbol)

            current = prices.get(symbol) or 0
            if current <= 0:
                continue

            raw_return = round(((current - snapshot) / snapshot) * 100, 4)
            directional_return = raw_return
            if r.get("directional_bias") == "BEARISH":
                directional_return = round(-raw_return, 4)

            scored.append({
                "symbol": symbol,
                "directional_bias": r.get("directional_bias"),
                "candidate_result": r.get("result"),
                "snapshot_price": snapshot,
                "current_price": current,
                "age_hours": age_hours,
                "raw_return_pct": raw_return,
                "directional_return_pct": directional_return,
                "prediction_correct": directional_return > 0,
            })

        correct = len([x for x in scored if x.get("prediction_correct")])
        avg_return = round(sum(x.get("directional_return_pct", 0) for x in scored) / len(scored), 4) if scored else 0
        accuracy = round((correct / len(scored)) * 100, 2) if scored else 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "HorizonOneHourPerformanceEngine",
            "eligible_predictions": len(scored),
            "correct_predictions": correct,
            "accuracy_pct": accuracy,
            "average_directional_return_pct": avg_return,
            "latest_scored": scored[-25:],
            "status": "HORIZON_ONE_HOUR_PERFORMANCE_READY",
        }
