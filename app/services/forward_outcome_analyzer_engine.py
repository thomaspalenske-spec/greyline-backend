import json
from datetime import datetime
from pathlib import Path


class ForwardOutcomeAnalyzerEngine:
    def __init__(self):
        self.ledger_file = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")

    def analyze(self, limit=500):
        if not self.ledger_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "record_count": 0,
                "pending_outcomes": 0,
                "status": "NO_FORWARD_OUTCOME_RECORDS",
            }

        lines = self.ledger_file.read_text().splitlines()
        records = [json.loads(x) for x in lines[-limit:] if x.strip()]

        executed = [r for r in records if r.get("result") == "EXECUTE"]
        watched = [r for r in records if r.get("result") == "WATCH"]
        pending = [r for r in records if r.get("outcome_status") == "PENDING_FORWARD_OUTCOME"]

        by_symbol = {}
        for r in records:
            symbol = r.get("symbol") or "UNKNOWN"
            by_symbol.setdefault(symbol, 0)
            by_symbol[symbol] += 1

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ForwardOutcomeAnalyzerEngine",
            "record_count": len(records),
            "executed_candidate_count": len(executed),
            "watch_candidate_count": len(watched),
            "pending_outcomes": len(pending),
            "symbols_tracked": by_symbol,
            "learning_status": "FORWARD_PRICE_OUTCOMES_NOT_YET_ATTACHED",
            "status": "FORWARD_OUTCOME_ANALYZER_READY",
        }
