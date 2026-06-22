from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class AsymmetryScoringEngine:
    _quote_cache = {}

    def _quote(self, symbol):
        symbol = symbol.upper().strip()
        if symbol in self._quote_cache:
            return dict(self._quote_cache[symbol])
        result = TradeStationQuoteLiveEngine().get_quote(symbol)
        self._quote_cache[symbol] = dict(result)
        return result

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
                "asymmetry_score": 50,
                "asymmetry_state": "QUOTE_UNAVAILABLE",
                "execution_enabled": False,
                "status": "ASYMMETRY_SCORE_DEGRADED"
            }

        quote = (quote_result.get("response_json", {}).get("Quotes") or [{}])[0]

        last = self._float(quote.get("Last"))
        high = self._float(quote.get("High"))
        low = self._float(quote.get("Low"))
        vwap = self._float(quote.get("VWAP"))
        net_change_pct = self._float(quote.get("NetChangePct"))

        score = 60
        reasons = []

        if vwap and last > vwap:
            score += 15
            reasons.append("PRICE_ABOVE_VWAP")
        else:
            score -= 12
            reasons.append("PRICE_BELOW_VWAP")

        day_range = high - low if high and low else 0
        close_location = 0.5

        if day_range > 0:
            close_location = (last - low) / day_range

        if close_location >= 0.75:
            score += 15
            reasons.append("CLOSE_NEAR_HIGH")
        elif close_location <= 0.25:
            score -= 15
            reasons.append("CLOSE_NEAR_LOW")

        if net_change_pct >= 2:
            score += 10
            reasons.append("UPSIDE_MOMENTUM")
        elif net_change_pct <= -3:
            score -= 15
            reasons.append("DOWNSIDE_MOMENTUM")

        score = max(0, min(100, score))

        if score >= 85:
            asymmetry_state = "ELITE_ASYMMETRY_LIVE"
        elif score >= 75:
            asymmetry_state = "STRONG_ASYMMETRY_LIVE"
        elif score >= 60:
            asymmetry_state = "DEVELOPING_ASYMMETRY_LIVE"
        else:
            asymmetry_state = "WEAK_ASYMMETRY_LIVE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "asymmetry_score": round(score, 2),
            "asymmetry_state": asymmetry_state,
            "asymmetry_reasons": reasons,
            "asymmetry_context": {
                "last": last,
                "high": high,
                "low": low,
                "vwap": vwap,
                "net_change_pct": net_change_pct,
                "close_location": round(close_location, 4),
            },
            "execution_enabled": False,
            "status": "ASYMMETRY_SCORE_READY"
        }
