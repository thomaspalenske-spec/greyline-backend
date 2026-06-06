from datetime import datetime

from app.services.master_decision_history_engine import MasterDecisionHistoryEngine


class DecisionReplayEngine:

    def replay_recent_decisions(self, limit=20):
        history = MasterDecisionHistoryEngine().get_history(limit=limit)
        events = history.get("events", [])

        replayed = []

        for event in events:
            decision = event.get("decision")
            top_candidate = event.get("top_candidate") or {}

            replay_state = "NO_ACTION_REPLAY"

            if decision == "EXECUTE_SIGNAL_BLOCKED_READ_ONLY":
                replay_state = "WOULD_HAVE_SIGNALLED_EXECUTE"
            elif decision == "NO_ACTION":
                replay_state = "NO_ACTION_REPLAY"

            replayed.append({
                "original_timestamp": event.get("timestamp"),
                "decision": decision,
                "decision_reason": event.get("decision_reason"),
                "symbol": top_candidate.get("symbol"),
                "composite_score": top_candidate.get("composite_score"),
                "broker_ready": event.get("broker_ready"),
                "risk_state": event.get("risk_state"),
                "governor_status": event.get("governor_status"),
                "replay_state": replay_state,
                "execution_enabled": False,
                "order_placement_allowed": False
            })

        execute_signal_count = len([
            item for item in replayed
            if item.get("replay_state") == "WOULD_HAVE_SIGNALLED_EXECUTE"
        ])

        no_action_count = len([
            item for item in replayed
            if item.get("replay_state") == "NO_ACTION_REPLAY"
        ])

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "MASTER_DECISION_HISTORY_REPLAY",
            "events_replayed": len(replayed),
            "execute_signal_count": execute_signal_count,
            "no_action_count": no_action_count,
            "replayed_decisions": replayed,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_REPLAY_COMPLETE"
        }
