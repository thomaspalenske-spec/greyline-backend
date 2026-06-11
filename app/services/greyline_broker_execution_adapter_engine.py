from datetime import datetime


class GreyLineBrokerExecutionAdapterEngine:

    def __init__(self, mode="SIMULATION"):
        self.mode = mode

    def submit_order(self, symbol, quantity, side="BUY", price=None):

        # -------------------------
        # SAFETY PLACEHOLDER
        # -------------------------
        if self.mode == "SIMULATION":

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "quantity": quantity,
                "side": side,
                "price": price,
                "broker": "SIMULATED_BROKER",
                "status": "ORDER_SIMULATED",
                "execution_id": f"SIM-{datetime.utcnow().timestamp()}"
            }

        # -------------------------
        # LIVE MODE (NOT CONNECTED YET)
        # -------------------------
        if self.mode == "LIVE":

            # This is where TradeStation / IBKR / Alpaca will connect
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "quantity": quantity,
                "side": side,
                "price": price,
                "broker": "LIVE_BROKER_PENDING",
                "status": "LIVE_EXECUTION_NOT_IMPLEMENTED",
                "execution_id": None
            }

        return {
            "status": "INVALID_BROKER_MODE",
            "mode": self.mode
        }
