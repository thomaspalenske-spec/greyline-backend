from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class SetupScoringEngine:

    def _float(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()
        quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)

        if quote_result.get("http_status") != 200:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "setup_score": 50,
                "setup_tier": "QUOTE_UNAVAILABLE",
                "execution_enabled": False,
                "status": "SETUP_SCORE_DEGRADED"
            }

        quotes = quote_result.get("response_json", {}).get("Quotes", [])
        quote = quotes[0] if quotes else {}

        last = self._float(quote.get("Last"))
        open_price = self._float(quote.get("Open"))
        high = self._float(quote.get("High"))
        low = self._float(quote.get("Low"))
        previous_close = self._float(quote.get("PreviousClose"))
        vwap = self._float(quote.get("VWAP"))
        net_change_pct = self._float(quote.get("NetChangePct"))

        score = 60
        reasons = []

        if previous_close and last > previous_close:
            score += 12
            reasons.append("ABOVE_PREVIOUS_CLOSE")
        else:
            score -= 10
            reasons.append("BELOW_PREVIOUS_CLOSE")

        if vwap and last > vwap:
            score += 12
            reasons.append("ABOVE_VWAP")
        else:
            score -= 10
            reasons.append("BELOW_VWAP")

        if open_price and last > open_price:
            score += 8
            reasons.append("ABOVE_OPEN")
        else:
            score -= 6
            reasons.append("BELOW_OPEN")

        intraday_range = high - low if high and low else 0
        close_location = 0.5

        if intraday_range > 0:
            close_location = (last - low) / intraday_range

        if close_location >= 0.75:
            score += 10
            reasons.append("CLOSE_NEAR_HIGH")
        elif close_location <= 0.25:
            score -= 10
            reasons.append("CLOSE_NEAR_LOW")

        if net_change_pct <= -3:
            score -= 12
            reasons.append("SHARP_DAILY_DECLINE")
        elif net_change_pct >= 2:
            score += 8
            reasons.append("STRONG_DAILY_ADVANCE")

        score = max(0, min(100, score))

        if score >= 85:
            setup_tier = "ELITE_LIVE"
        elif score >= 75:
            setup_tier = "STRONG_LIVE"
        elif score >= 60:
            setup_tier = "DEVELOPING_LIVE"
        else:
            setup_tier = "WEAK_LIVE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "setup_score": round(score, 2),
            "setup_tier": setup_tier,
            "setup_reasons": reasons,
            "setup_context": {
                "last": last,
                "open": open_price,
                "high": high,
                "low": low,
                "previous_close": previous_close,
                "vwap": vwap,
                "net_change_pct": net_change_pct,
                "close_location": round(close_location, 4),
            },
            "execution_enabled": False,
            "status": "SETUP_SCORE_READY"
        }
