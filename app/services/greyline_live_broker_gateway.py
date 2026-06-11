class LiveBrokerGateway:
    def __init__(self, broker="UNCONFIGURED", api_key=None):
        self.broker = broker
        self.api_key = api_key

    def validate(self):
        return {
            "authorized": self.api_key is not None,
            "broker": self.broker
        }

    def submit_order(self, order):
        if not self.api_key:
            return {
                "status": "BLOCKED_NO_API_KEY",
                "live": False
            }

        return {
            "status": "LIVE_ORDER_GATE_READY",
            "broker": self.broker,
            "order": order
        }
