class LiveMarketDataGateway:
    def __init__(self, provider="UNCONFIGURED"):
        self.provider = provider

    def connect(self):
        return {
            "status": "CONNECTED" if self.provider != "UNCONFIGURED" else "NOT_CONFIGURED",
            "provider": self.provider
        }

    def stream_tick(self, symbol):
        return {
            "symbol": symbol,
            "price": None,
            "status": "LIVE_STREAM_NOT_IMPLEMENTED"
        }
