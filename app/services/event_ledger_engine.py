from datetime import datetime


class EventLedgerEngine:

    def create_event(
        self,
        trade_id,
        event_type,
        payload
    ):

        return {
            "trade_id": trade_id,
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "payload": payload
        }
