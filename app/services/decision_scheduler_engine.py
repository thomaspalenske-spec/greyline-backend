from datetime import datetime

from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine
from app.services.master_decision_history_engine import MasterDecisionHistoryEngine


class DecisionSchedulerEngine:

    def status(self, limit=50):
        history = MasterDecisionHistoryEngine().get_history(limit=limit)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_SCHEDULER",
            "scheduler_enabled": False,
            "automatic_background_execution": False,
            "manual_cycle_available": True,
            "events_logged": history.get("event_count", 0),
            "last_run": (
                history.get("events", [])[-1].get("timestamp")
                if history.get("events") else None
            ),
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_SCHEDULER_READY",
        }

    def run_manual_cycle(self):
        result = GreyLineMasterDecisionEngine().evaluate()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_SCHEDULER_MANUAL_CYCLE",
            "cycle_executed": True,
            "decision": result.get("decision"),
            "decision_reason": result.get("decision_reason"),
            "symbols_scored": result.get("symbols_scored"),
            "decision_event_logged": result.get("decision_event_logged"),
            "decision_event_log_status": result.get("decision_event_log_status"),
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_SCHEDULER_MANUAL_CYCLE_COMPLETE",
        }
