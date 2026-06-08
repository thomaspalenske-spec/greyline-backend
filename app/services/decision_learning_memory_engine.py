import json
from datetime import datetime
from pathlib import Path

from app.services.decision_learning_engine import DecisionLearningEngine
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class DecisionLearningMemoryEngine:

    def __init__(self):
        self.log_dir = Path("app/data/learning")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "decision_learning_history.jsonl"

    def record_current_learning(self, limit=50):
        learning = DecisionLearningEngine().analyze(limit=limit)
        recommendations = learning.get("recommendations", [])

        recorded = 0

        with self.log_file.open("a") as f:
            for item in recommendations:
                event = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "source": "DECISION_LEARNING_MEMORY",
                    "decision_timestamp": item.get("decision_timestamp"),
                    "symbol": item.get("symbol"),
                    "decision": item.get("decision"),
                    "score_result": item.get("score_result"),
                    "move_pct": item.get("move_pct"),
                    "learning_adjustment": item.get("learning_adjustment"),
                    "learning_rationale": item.get("learning_rationale"),
                    "automatic_weight_changes_enabled": False,
                    "human_approval_required": True,
                    "execution_enabled": False,
                    "order_placement_allowed": False,
                }
                f.write(json.dumps(event) + "\n")
                ImmutableAuditLedgerEngine().record(
                    "DECISION_LEARNING_EVENT",
                    {
                        "decision_timestamp": event.get("decision_timestamp"),
                        "symbol": event.get("symbol"),
                        "decision": event.get("decision"),
                        "score_result": event.get("score_result"),
                        "learning_adjustment": event.get("learning_adjustment"),
                    },
                )
                recorded += 1

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_LEARNING_MEMORY",
            "events_recorded": recorded,
            "log_file": str(self.log_file),
            "automatic_weight_changes_enabled": False,
            "human_approval_required": True,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_LEARNING_MEMORY_RECORDED",
        }

    def get_history(self, limit=50):
        if not self.log_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": "GreyLine",
                "source": "DECISION_LEARNING_MEMORY",
                "events_found": False,
                "event_count": 0,
                "events": [],
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "NO_DECISION_LEARNING_HISTORY_FOUND",
            }

        lines = self.log_file.read_text().splitlines()
        recent_lines = lines[-limit:]

        events = []
        for line in recent_lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_LEARNING_MEMORY",
            "events_found": len(events) > 0,
            "event_count": len(events),
            "events": events,
            "automatic_weight_changes_enabled": False,
            "human_approval_required": True,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_LEARNING_HISTORY_READY",
        }
