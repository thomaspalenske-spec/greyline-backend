from datetime import datetime


class GreyLineBrokerInterfaceEngine:

    def __init__(self, mode="SIMULATION"):
        self.mode = mode

    def submit_order(self, symbol, quantity, side="BUY", price=None):

        if self.mode == "SIMULATION":
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "quantity": quantity,
                "side": side,
                "price": price,
                "status": "SIMULATED_ORDER_ACCEPTED"
            }

        # Placeholder for live broker integration (TradeStation / IBKR)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "price": price,
            "status": "LIVE_ORDER_ROUTED",
            "note": "BROKER INTEGRATION NOT CONNECTED YET"
        }
