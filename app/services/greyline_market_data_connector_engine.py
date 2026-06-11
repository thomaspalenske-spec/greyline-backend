from datetime import datetime
import random


class GreyLineMarketDataConnectorEngine:

    def __init__(self, provider="SIMULATION"):

        self.provider = provider

    def fetch_tick(self, symbol="NVDA"):

        # -------------------------
        # SIMULATION PROVIDER
        # -------------------------
        if self.provider == "SIMULATION":

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "price": round(100 + random.uniform(-3, 3), 2),
                "volume": random.randint(100, 2000),
                "bid": round(100 + random.uniform(-3, 3), 2),
                "ask": round(100 + random.uniform(-3, 3), 2),
                "source": "SIMULATED_CONNECTOR",
                "status": "TICK_READY"
            }

        # -------------------------
        # LIVE PROVIDER PLACEHOLDER
        # -------------------------
        if self.provider == "LIVE":

            # This is where Polygon / IBKR / TradeStation will plug in
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "price": None,
                "volume": None,
                "bid": None,
                "ask": None,
                "source": "LIVE_CONNECTOR_NOT_IMPLEMENTED",
                "status": "LIVE_FEED_PENDING_INTEGRATION"
            }

        return {
            "status": "INVALID_PROVIDER",
            "provider": self.provider
        }

    def generate_stream(self, n=5, symbol="NVDA"):

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "provider": self.provider,
            "events": [self.fetch_tick(symbol) for _ in range(n)],
            "event_count": n,
            "status": "CONNECTOR_STREAM_READY"
        }
