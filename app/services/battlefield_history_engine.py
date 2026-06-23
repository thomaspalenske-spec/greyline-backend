import json
from pathlib import Path
from datetime import datetime


class BattlefieldHistoryEngine:
    def __init__(self):
        self.path = Path("app/data/market_battlefield/battlefield_history.jsonl")

    def record(self, battlefield):
        self.path.parent.mkdir(parents=True, exist_ok=True)

        best_call = battlefield.get("best_call", {}) or {}
        best_put = battlefield.get("best_put", {}) or {}

        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "battlefield_health": battlefield.get("battlefield_health"),
            "battlefield_health_reason": battlefield.get("battlefield_health_reason"),
            "market_bias": battlefield.get("market_bias"),
            "symbols_scored": battlefield.get("symbols_scored"),
            "ready_call_count": battlefield.get("ready_call_count"),
            "ready_put_count": battlefield.get("ready_put_count"),
            "best_call_symbol": best_call.get("symbol"),
            "best_call_score": best_call.get("score") or best_call.get("composite_score"),
            "best_call_flow_confirmation": best_call.get("flow_confirmation"),
            "best_call_flow_strength": best_call.get("flow_strength"),
            "best_put_symbol": best_put.get("symbol"),
            "best_put_score": best_put.get("score") or best_put.get("composite_score"),
            "best_put_flow_confirmation": best_put.get("flow_confirmation"),
            "best_put_flow_strength": best_put.get("flow_strength"),
            "status": "BATTLEFIELD_HISTORY_RECORDED",
        }

        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")

        return row

    def history(self, limit=50):
        if not self.path.exists():
            return []

        rows = []
        for line in self.path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue

        return rows[-limit:]
