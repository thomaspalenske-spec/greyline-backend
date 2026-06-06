from datetime import datetime

from app.services.decision_replay_engine import DecisionReplayEngine


class DecisionPerformanceAttributionEngine:

    def analyze(self, limit=50):
        replay = DecisionReplayEngine().replay_recent_decisions(limit=limit)

        decisions = replay.get("replayed_decisions", [])

        attribution = []

        no_action_count = 0
        execute_signal_count = 0

        for item in decisions:

            replay_state = item.get("replay_state")

            if replay_state == "NO_ACTION_REPLAY":
                classification = "NO_ACTION_RECORDED"
                no_action_count += 1

            elif replay_state == "WOULD_HAVE_SIGNALLED_EXECUTE":
                classification = "EXECUTE_SIGNAL_RECORDED"
                execute_signal_count += 1

            else:
                classification = "UNKNOWN"

            attribution.append({
                "timestamp": item.get("original_timestamp"),
                "decision": item.get("decision"),
                "symbol": item.get("symbol"),
                "replay_state": replay_state,
                "classification": classification
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_PERFORMANCE_ATTRIBUTION",
            "events_analyzed": len(attribution),
            "no_action_count": no_action_count,
            "execute_signal_count": execute_signal_count,
            "attribution": attribution,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_ATTRIBUTION_READY"
        }
