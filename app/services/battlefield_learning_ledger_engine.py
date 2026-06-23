import json
from datetime import datetime
from pathlib import Path


class BattlefieldLearningLedgerEngine:
    def __init__(self):
        self.data_dir = Path("app/data/battlefield_learning")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.data_dir / "battlefield_learning_ledger.jsonl"

    def record(self, learning, quality_gate, adaptive_advisor):
        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "sample_count": learning.get("sample_count"),
            "learning_state": learning.get("learning_state"),
            "top_performing_symbols": learning.get("top_performing_symbols"),
            "worst_performing_symbols": learning.get("worst_performing_symbols"),
            "direction_performance": learning.get("direction_performance"),
            "candidate_result_performance": learning.get("candidate_result_performance"),
            "quality_score": quality_gate.get("quality_score"),
            "quality_state": quality_gate.get("quality_state"),
            "quality_warnings": quality_gate.get("warnings"),
            "auto_adaptation_allowed": quality_gate.get("auto_adaptation_allowed"),
            "adaptive_recommendations": adaptive_advisor.get("recommendations"),
            "status": "BATTLEFIELD_LEARNING_LEDGER_RECORD",
        }

        with self.ledger_file.open("a") as f:
            f.write(json.dumps(row) + "\n")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "BattlefieldLearningLedgerEngine",
            "recorded": True,
            "ledger": str(self.ledger_file),
            "status": "BATTLEFIELD_LEARNING_LEDGER_RECORDED",
        }

    def history(self, limit=100):
        if not self.ledger_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "record_count": 0,
                "records": [],
                "status": "NO_BATTLEFIELD_LEARNING_LEDGER_RECORDS",
            }

        lines = self.ledger_file.read_text().splitlines()
        records = [json.loads(x) for x in lines[-limit:] if x.strip()]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "BattlefieldLearningLedgerEngine",
            "record_count": len(records),
            "records": records,
            "status": "BATTLEFIELD_LEARNING_LEDGER_HISTORY_READY",
        }
