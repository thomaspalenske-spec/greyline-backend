class AbsorptionDetectionEngine:
    def _num(self, v, default=0.0):
        try:
            return float(v)
        except Exception:
            return default

    def evaluate(self, quote, tape):
        buy_volume = self._num(tape.get("buy_volume"))
        sell_volume = self._num(tape.get("sell_volume"))
        last = self._num(quote.get("last") or quote.get("Last"))
        open_price = self._num(quote.get("open") or quote.get("Open") or last)

        state = "NONE"
        score = 50.0

        if sell_volume > buy_volume and last >= open_price:
            state = "BUYER_ABSORBING"
            score = 90.0
        elif buy_volume > sell_volume and last <= open_price:
            state = "SELLER_ABSORBING"
            score = 90.0

        return {
            "engine": "AbsorptionDetectionEngine",
            "score": score,
            "state": state,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "status": "ABSORPTION_DETECTION_READY",
        }
