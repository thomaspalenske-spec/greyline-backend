class BidAskImbalanceEngine:
    def _num(self, v, default=0.0):
        try:
            return float(v)
        except Exception:
            return default

    def evaluate(self, quote):
        bid_size = self._num(quote.get("bid_size") or quote.get("BidSize"))
        ask_size = self._num(quote.get("ask_size") or quote.get("AskSize"))
        total = max(bid_size + ask_size, 1.0)
        ratio = bid_size / total
        score = round(max(0, min(100, ratio * 100)), 2)

        state = "BALANCED"
        if ratio >= 0.6:
            state = "BUYING_PRESSURE"
        elif ratio <= 0.4:
            state = "SELLING_PRESSURE"

        return {
            "engine": "BidAskImbalanceEngine",
            "score": score,
            "state": state,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "status": "BID_ASK_IMBALANCE_READY",
        }
