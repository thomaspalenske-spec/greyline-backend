class OrderBookPressureEngine:
    def _num(self, v, default=0.0):
        try:
            return float(v)
        except Exception:
            return default

    def evaluate(self, quote):
        bid_size = self._num(quote.get("bid_size") or quote.get("BidSize"))
        ask_size = self._num(quote.get("ask_size") or quote.get("AskSize"))
        total = max(bid_size + ask_size, 1.0)
        pressure = (bid_size - ask_size) / total
        score = round(max(0, min(100, 50 + pressure * 50)), 2)

        state = "BALANCED"
        if score >= 60:
            state = "BUY_DEPTH_ADVANTAGE"
        elif score <= 40:
            state = "SELL_DEPTH_ADVANTAGE"

        return {
            "engine": "OrderBookPressureEngine",
            "score": score,
            "state": state,
            "bid_depth": bid_size,
            "ask_depth": ask_size,
            "status": "ORDER_BOOK_PRESSURE_READY",
        }
