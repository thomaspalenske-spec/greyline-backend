from datetime import datetime
import random


class GreyLineEventStreamEngine:

    def generate_tick(self):

        tick = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": "NVDA",
            "price": round(100 + random.uniform(-2, 2), 2),
            "volume": random.randint(100, 1000),
            "event_type": "MARKET_TICK"
        }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "event": tick,
            "status": "EVENT_STREAM_TICK_GENERATED"
        }

    def generate_batch(self, count=5):

        events = []

        for _ in range(count):
            events.append(self.generate_tick()["event"])

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "event_count": len(events),
            "events": events,
            "status": "EVENT_STREAM_BATCH_READY"
        }
