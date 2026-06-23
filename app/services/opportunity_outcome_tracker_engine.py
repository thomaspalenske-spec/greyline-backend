import json
from datetime import datetime
from pathlib import Path


class OpportunityOutcomeTrackerEngine:
    def __init__(self):
        self.data_dir = Path("app/data/opportunity_memory")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.data_dir / "opportunity_outcome_ledger.jsonl"

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
