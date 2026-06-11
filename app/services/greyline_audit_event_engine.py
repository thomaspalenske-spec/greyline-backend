from datetime import datetime
import json


class GreyLineAuditEventEngine:

    def __init__(self):

        self.events = []

    def log_event(self, event_type, payload):

        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "payload": payload
        }

        self.events.append(event)

        return event

    def export_log(self):

        return {
            "status": "AUDIT_LOG_EXPORTED",
            "event_count": len(self.events),
            "events": self.events
        }

    def replay(self):

        replay_state = {
            "positions": [],
            "states": [],
            "decisions": []
        }

        for event in self.events:

            etype = event["event_type"]

            if etype == "STATE_CHANGE":
                replay_state["states"].append(event)

            if etype == "TRADE_EXECUTED":
                replay_state["decisions"].append(event)

            if etype == "POSITION_UPDATE":
                replay_state["positions"].append(event)

        return {
            "status": "REPLAY_COMPLETE",
            "reconstructed_state": replay_state,
            "event_count": len(self.events)
        }
