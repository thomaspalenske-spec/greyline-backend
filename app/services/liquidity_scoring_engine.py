from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class LiquidityScoringEngine:
    def _quote(self, symbol):
        return TradeStationQuoteLiveEngine().get_quote(
            symbol.upper().strip()
        )

    def _float(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()
        quote_result = self._quote(symbol)

        if quote_result.get("http_status") != 200:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "liquidity_score": 50,
                "liquidity_tier": "QUOTE_UNAVAILABLE",
                "execution_enabled": False,
                "status": "LIQUIDITY_SCORE_DEGRADED"
            }

        quote = (quote_result.get("response_json", {}).get("Quotes") or [{}])[0]

        last = self._float(quote.get("Last"))
        bid = self._float(quote.get("Bid"))
        ask = self._float(quote.get("Ask"))
        bid_size = self._float(quote.get("BidSize"))
        ask_size = self._float(quote.get("AskSize"))
        volume = self._float(quote.get("Volume"))
        previous_volume = self._float(quote.get("PreviousVolume"))

        spread_pct = ((ask - bid) / last) * 100 if last and bid and ask else 0.0
        volume_ratio = volume / previous_volume if previous_volume else 0.0

        score = 70
        reasons = []

        if spread_pct <= 0.03:
            score += 18
            reasons.append("VERY_TIGHT_SPREAD")
        elif spread_pct <= 0.08:
            score += 10
            reasons.append("TIGHT_SPREAD")
        elif spread_pct >= 0.25:
            score -= 20
            reasons.append("WIDE_SPREAD")
        elif spread_pct >= 0.10:
            score -= 10
            reasons.append("MODERATE_SPREAD")

        if volume_ratio >= 1:
            score += 12
            reasons.append("VOLUME_AT_OR_ABOVE_PREVIOUS")
        elif volume_ratio >= 0.60:
            score += 5
            reasons.append("ADEQUATE_VOLUME")
        elif volume_ratio < 0.35:
            score -= 12
            reasons.append("LOW_VOLUME_PARTICIPATION")

        if bid_size + ask_size >= 1000:
            score += 5
            reasons.append("VISIBLE_DEPTH_PRESENT")
        elif bid_size + ask_size <= 100:
            score -= 5
            reasons.append("LIMITED_VISIBLE_DEPTH")

        score = max(0, min(100, score))

        if score >= 85:
            tier = "HIGH_LIVE"
        elif score >= 70:
            tier = "MEDIUM_LIVE"
        elif score >= 50:
            tier = "LOW_LIVE"
        else:
            tier = "POOR_LIVE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "liquidity_score": round(score, 2),
            "liquidity_tier": tier,
            "liquidity_reasons": reasons,
            "liquidity_context": {
                "last": last,
                "bid": bid,
                "ask": ask,
                "spread_pct": round(spread_pct, 4),
                "bid_size": bid_size,
                "ask_size": ask_size,
                "volume": volume,
                "previous_volume": previous_volume,
                "volume_ratio": round(volume_ratio, 4),
            },
            "execution_enabled": False,
            "status": "LIQUIDITY_SCORE_READY"
        }
