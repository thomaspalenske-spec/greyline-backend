from datetime import datetime
import random


class GreyLineMarketDataIngestionEngine:

    def __init__(self, mode="SIMULATION"):
        self.mode = mode

    def fetch_tick(self, symbol="NVDA"):

        # SAFE DEFAULT: simulated fallback
        if self.mode == "SIMULATION":

            price = round(100 + random.uniform(-2, 2), 2)
            volume = random.randint(100, 1000)

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "price": price,
                "volume": volume,
                "source": "SIMULATED_MARKET_FEED",
                "status": "TICK_GENERATED"
            }

        # LIVE MODE PLACEHOLDER (ready for real API integration)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "price": None,
            "volume": None,
            "source": "LIVE_FEED_NOT_CONNECTED",
            "status": "LIVE_DATA_LAYER_READY"
        }

    def generate_batch(self, n=5, symbol="NVDA"):

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "events": [self.fetch_tick(symbol) for _ in range(n)],
            "event_count": n,
            "status": "MARKET_DATA_BATCH_READY"
        }
