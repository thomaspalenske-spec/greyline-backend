from datetime import datetime


class BaseBrokerAdapter:

    def submit_order(self, symbol, quantity, side, price=None):
        raise NotImplementedError


class PaperBrokerAdapter(BaseBrokerAdapter):

    def submit_order(self, symbol, quantity, side, price=None):

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "price": price,
            "broker": "PAPER",
            "status": "PAPER_ORDER_EXECUTED"
        }


class LiveBrokerAdapter(BaseBrokerAdapter):

    def __init__(self, broker_name="UNCONFIGURED"):

        self.broker_name = broker_name

    def submit_order(self, symbol, quantity, side, price=None):

        # PLACEHOLDER FOR REAL BROKER CALLS
        # (TradeStation / IBKR / Alpaca REST or WebSocket APIs)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "price": price,
            "broker": self.broker_name,
            "status": "LIVE_ORDER_ROUTED_NOT_IMPLEMENTED",
            "execution_id": None
        }


class BrokerRouter:

    def __init__(self, mode="PAPER"):

        self.mode = mode
        self.paper = PaperBrokerAdapter()
        self.live = LiveBrokerAdapter("LIVE_BROKER")

    def get_adapter(self):

        if self.mode == "LIVE":
            return self.live

        return self.paper
