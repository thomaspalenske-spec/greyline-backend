import json
from datetime import datetime
from pathlib import Path

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class OpportunityOutcomeTrackerEngine:
    def __init__(self):
        self.data_dir = Path("app/data/opportunity_memory")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.data_dir / "opportunity_outcome_ledger.jsonl"

    def _last_price(self, symbol):
        quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)
        quotes = (quote_result.get("response_json") or {}).get("Quotes") or []
        row = quotes[0] if quotes else {}

        try:
            return float(row.get("Last") or 0)
        except Exception:
            return 0.0

    def record(self, candidates):
        rows = []

        for item in candidates or []:
            rows.append({
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": item.get("symbol"),
                "option_type": item.get("option_type"),
                "result": item.get("result"),
                "score": item.get("score"),
                "liquidity_score": item.get("liquidity_score"),
                "score_distance_to_execute": item.get("score_distance_to_execute"),
                "directional_bias": item.get("directional_bias"),
                "rank": item.get("rank"),
                "snapshot_price": self._last_price(item.get("symbol")),
                "outcome_status": "PENDING_FORWARD_OUTCOME"
            })

        if rows:
            with self.ledger_file.open("a") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")

        return {
            "records_written": len(rows),
            "status": "OPPORTUNITY_OUTCOME_TRACKER_RECORDED"
        }
