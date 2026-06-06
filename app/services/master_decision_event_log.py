import json
from datetime import datetime
from pathlib import Path


class MasterDecisionEventLog:

    def __init__(self):
        self.log_dir = Path("app/data/master_decisions")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "master_decision_events.jsonl"

    def record_decision(self, decision_result):
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "decision": decision_result.get("decision"),
            "decision_reason": decision_result.get("decision_reason"),
            "broker_ready": decision_result.get("broker_ready"),
            "risk_state": decision_result.get("risk_state"),
            "symbols_scored": decision_result.get("symbols_scored"),
            "top_candidate": decision_result.get("top_candidate"),
            "governor_status": decision_result.get("governor", {}).get("status"),
            "execution_enabled": False,
            "order_placement_allowed": False
        }

        with self.log_file.open("a") as f:
            f.write(json.dumps(event) + "\n")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "event_logged": True,
            "log_file": str(self.log_file),
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "MASTER_DECISION_EVENT_LOGGED"
        }
