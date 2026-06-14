class IBKRMarketDataEngine:
    def __init__(self, config):
        self.config = config

    def connect(self):
        return {
            "status": "IBKR_CONNECTED_SIMULATION_SAFE",
            "mode": self.config.mode
        }

    def get_tick(self, symbol):
        # placeholder for IBKR streaming API
        return {
            "symbol": symbol,
            "price": None,
            "status": "NO_LIVE_FEED_CONNECTED"
        }
