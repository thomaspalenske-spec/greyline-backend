class SimulationSignalEngine:
    """
    Converts replayed historical OHLCV data into a no-lookahead candidate.

    First version:
    - Uses same-day OHLCV only.
    - Does not inspect future bars.
    """

    def evaluate(self, market_data):
        market_data = market_data or {}

        close = self._num(market_data.get("close"))
        open_price = self._num(market_data.get("open"))
        high = self._num(market_data.get("high"))
        low = self._num(market_data.get("low"))
        volume = self._num(market_data.get("volume"))

        if close is None or open_price is None or high is None or low is None:
            return {
                "candidate_available": False,
                "reason": "NO_REPLAY_MARKET_DATA",
                "status": "SIMULATION_SIGNAL_NO_DATA",
            }
            return {
                "candidate_available": False,
                "reason": "NO_REPLAY_MARKET_DATA",
                "status": "SIMULATION_SIGNAL_NO_DATA",
            }

        intraday_return = ((close - open_price) / open_price) * 100 if open_price else 0
        range_pct = ((high - low) / open_price) * 100 if high is not None and low is not None and open_price else 0

        adjusted_score = min(100, max(0, 50 + intraday_return * 8 + range_pct * 2))
        liquidity_score = 90 if volume and volume > 0 else 0
        direction_confidence = min(100, max(0, 50 + intraday_return * 10))

        option_type = "CALL" if intraday_return >= 0 else "PUT"
        directional_bias = "BULLISH" if option_type == "CALL" else "BEARISH"

        return {
            "candidate_available": True,
            "symbol": market_data.get("symbol"),
            "option_type": option_type,
            "directional_bias": directional_bias,
            "adjusted_score": round(adjusted_score, 2),
            "liquidity_score": liquidity_score,
            "signal_reliability_score": round(min(100, max(0, 60 + range_pct * 3)), 2),
            "direction_confidence": round(direction_confidence, 2),
            "setup_score": round(min(100, max(0, 50 + abs(intraday_return) * 10)), 2),
            "source": "SIMULATION_OHLCV_NO_LOOKAHEAD",
            "status": "SIMULATION_SIGNAL_READY",
        }

    @staticmethod
    def _num(value):
        try:
            return float(value) if value not in [None, ""] else None
        except Exception:
            return None
