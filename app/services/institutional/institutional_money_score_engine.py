from datetime import datetime


class InstitutionalMoneyScoreEngine:
    """
    First-pass institutional money intelligence engine.

    Current mode:
    - Uses available/inferred GreyLine fields.
    - Designed to accept direct feeds later:
      options_flow, dark_pool, dealer_gamma, order_flow, vwap.
    """

    def evaluate(self, candidate=None, feeds=None):
        candidate = candidate or {}
        feeds = feeds or {}

        symbol = candidate.get("symbol")
        option_type = candidate.get("option_type")
        directional_bias = candidate.get("directional_bias")

        liquidity = self._num(candidate.get("liquidity_score"))
        reliability = self._num(candidate.get("signal_reliability_score"))
        direction_confidence = self._num(candidate.get("direction_confidence"))
        setup = self._num(candidate.get("setup_score"))
        adjusted_score = self._num(candidate.get("adjusted_score") or candidate.get("score"))

        options_flow_score = self._feed_score(feeds.get("options_flow"), fallback=(liquidity * 0.4 + adjusted_score * 0.6))
        dark_pool_score = self._feed_score(feeds.get("dark_pool"), fallback=(setup * 0.5 + direction_confidence * 0.5))
        dealer_gamma_score = self._feed_score(feeds.get("dealer_gamma"), fallback=reliability)
        order_flow_score = self._feed_score(feeds.get("order_flow"), fallback=liquidity)
        vwap_score = self._feed_score(feeds.get("vwap"), fallback=setup)
        sponsorship_score = self._feed_score(feeds.get("institutional_sponsorship"), fallback=reliability)

        score = round(min(100, max(0,
            options_flow_score * 0.30 +
            dark_pool_score * 0.25 +
            dealer_gamma_score * 0.15 +
            vwap_score * 0.10 +
            order_flow_score * 0.10 +
            sponsorship_score * 0.10
        )), 2)

        direction = self._direction(option_type, directional_bias, direction_confidence)
        accumulation = self._state(score)
        distribution_risk = self._distribution_risk(score, direction_confidence, reliability)
        confidence = round(min(100, max(0, (reliability * 0.45 + direction_confidence * 0.35 + liquidity * 0.20))), 2)

        mode = "DIRECT_AND_INFERRED" if feeds else "INFERRED_ONLY"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "InstitutionalMoneyScoreEngine",
            "symbol": symbol,
            "option_type": option_type,
            "institutional_money_score": score,
            "institutional_direction": direction,
            "accumulation_state": accumulation,
            "distribution_risk": distribution_risk,
            "institutional_confidence": confidence,
            "flow_mode": mode,
            "components": {
                "options_flow_score": round(options_flow_score, 2),
                "dark_pool_score": round(dark_pool_score, 2),
                "dealer_gamma_score": round(dealer_gamma_score, 2),
                "vwap_score": round(vwap_score, 2),
                "order_flow_score": round(order_flow_score, 2),
                "sponsorship_score": round(sponsorship_score, 2),
            },
            "status": "INSTITUTIONAL_MONEY_SCORE_READY",
        }

    @staticmethod
    def _num(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def _feed_score(self, feed, fallback):
        if isinstance(feed, dict):
            return self._num(feed.get("score") or feed.get("institutional_score") or fallback)
        return self._num(fallback)

    @staticmethod
    def _direction(option_type, directional_bias, confidence):
        if confidence <= 0:
            return "UNKNOWN"
        opt = (option_type or "").upper()
        bias = (directional_bias or "").upper()
        if opt == "CALL" or "BULL" in bias:
            return "BULLISH"
        if opt == "PUT" or "BEAR" in bias:
            return "BEARISH"
        return "UNKNOWN"

    @staticmethod
    def _state(score):
        if score >= 90:
            return "EXTREME"
        if score >= 80:
            return "HIGH"
        if score >= 65:
            return "MODERATE"
        if score >= 50:
            return "LOW"
        return "WEAK"

    @staticmethod
    def _distribution_risk(score, confidence, reliability):
        risk = 100 - ((score * 0.5) + (confidence * 0.3) + (reliability * 0.2))
        risk = max(0, min(100, risk))
        if risk >= 70:
            return "HIGH"
        if risk >= 45:
            return "MODERATE"
        if risk >= 25:
            return "LOW"
        return "VERY_LOW"
