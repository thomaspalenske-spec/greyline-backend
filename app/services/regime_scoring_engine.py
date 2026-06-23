from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class RegimeScoringEngine:

    def _quote(self, symbol):
        return TradeStationQuoteLiveEngine().get_quote(symbol)

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()
        quote_result = self._quote(symbol)

        if quote_result.get("http_status") != 200:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "regime_score": 50,
                "regime": "QUOTE_UNAVAILABLE",
                "execution_enabled": False,
                "status": "REGIME_SCORE_DEGRADED"
            }

        quotes = quote_result.get("response_json", {}).get("Quotes", [])
        quote = quotes[0] if quotes else {}

        last = self._float(quote.get("Last"))
        previous_close = self._float(quote.get("PreviousClose"))
        vwap = self._float(quote.get("VWAP"))
        volume = self._float(quote.get("Volume"))
        previous_volume = self._float(quote.get("PreviousVolume"))
        net_change_pct = self._float(quote.get("NetChangePct"))

        market_flags = quote.get("MarketFlags", {}) or {}
        is_halted = market_flags.get("IsHalted") is True
        is_delayed = market_flags.get("IsDelayed") is True

        score = 60
        regime = "NEUTRAL_LIVE"

        if is_halted:
            score = 20
            regime = "HALTED"
        elif is_delayed:
            score = 45
            regime = "DELAYED_DATA"
        else:
            if previous_close and last > previous_close:
                score += 12
            elif previous_close and last < previous_close:
                score -= 10

            if vwap and last > vwap:
                score += 10
            elif vwap and last < vwap:
                score -= 8

            if previous_volume and volume > previous_volume:
                score += 6
            elif previous_volume and volume < previous_volume * 0.5:
                score -= 4

            if net_change_pct >= 2:
                score += 8
            elif net_change_pct <= -2:
                score -= 8

            score = max(0, min(100, score))

            if score >= 85:
                regime = "STRONG_LIVE_TREND"
            elif score >= 70:
                regime = "CONSTRUCTIVE_LIVE"
            elif score >= 50:
                regime = "NEUTRAL_LIVE"
            else:
                regime = "WEAK_LIVE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "regime_score": round(score, 2),
            "regime": regime,
            "last": last,
            "previous_close": previous_close,
            "vwap": vwap,
            "net_change_pct": net_change_pct,
            "volume": volume,
            "previous_volume": previous_volume,
            "execution_enabled": False,
            "status": "REGIME_SCORE_READY"
        }


    @staticmethod
    def _float(value):
        try:
            return float(value)
        except Exception:
            return 0.0
