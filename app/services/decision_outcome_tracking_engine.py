from datetime import datetime

from app.services.decision_replay_engine import DecisionReplayEngine


class DecisionOutcomeTrackingEngine:

    def analyze(self, limit=50):
        replay = DecisionReplayEngine().replay_recent_decisions(limit=limit)
        decisions = replay.get("replayed_decisions", [])

        outcomes = []

        no_action_good_skip = 0
        no_action_needs_review = 0
        execute_signal_pending = 0

        for item in decisions:
            decision = item.get("decision")
            replay_state = item.get("replay_state")
            symbol = item.get("symbol")

            outcome_status = "PENDING_REVIEW"
            outcome_reason = "No forward outcome data attached yet"

            if replay_state == "NO_ACTION_REPLAY":
                outcome_status = "GOOD_SKIP_PENDING_VALIDATION"
                outcome_reason = "NO_ACTION recorded; future price/outcome validation not yet attached"
                no_action_good_skip += 1

            elif replay_state == "WOULD_HAVE_SIGNALLED_EXECUTE":
                outcome_status = "EXECUTE_SIGNAL_PENDING_VALIDATION"
                outcome_reason = "Read-only execute signal recorded; future result not yet attached"
                execute_signal_pending += 1

            else:
                no_action_needs_review += 1

            outcomes.append({
                "timestamp": item.get("original_timestamp"),
                "decision": decision,
                "symbol": symbol,
                "replay_state": replay_state,
                "outcome_status": outcome_status,
                "outcome_reason": outcome_reason,
                "execution_enabled": False,
                "order_placement_allowed": False,
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_OUTCOME_TRACKING",
            "events_analyzed": len(outcomes),
            "no_action_good_skip_pending_validation": no_action_good_skip,
            "no_action_needs_review": no_action_needs_review,
            "execute_signal_pending_validation": execute_signal_pending,
            "outcomes": outcomes,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_OUTCOME_TRACKING_READY",
        }
