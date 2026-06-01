class TradingSignalEngine:
    def __init__(self):
        pass

    def evaluate(self, market_data=None):
        """
        Simple baseline signal engine
        """

        if not market_data:
            return {
                "signal": "NO_DATA",
                "confidence": 0.0,
                "reason": "No market data provided"
            }

        price = market_data.get("price", 0)
        trend = market_data.get("trend", "flat")

        if trend == "up":
            return {
                "signal": "BUY",
                "confidence": 0.65,
                "reason": "Uptrend detected"
            }

        if trend == "down":
            return {
                "signal": "SELL",
                "confidence": 0.65,
                "reason": "Downtrend detected"
            }

        return {
            "signal": "HOLD",
            "confidence": 0.5,
            "reason": "No clear direction"
        }
