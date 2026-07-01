from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class TrendPersistenceScoringEngine:
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
                "trend_persistence_score": 50,
                "trend_state": "QUOTE_UNAVAILABLE",
                "execution_enabled": False,
                "status": "TREND_PERSISTENCE_SCORE_DEGRADED"
            }

        quote = (quote_result.get("response_json", {}).get("Quotes") or [{}])[0]

        last = self._float(quote.get("Last"))
        high = self._float(quote.get("High"))
        low = self._float(quote.get("Low"))
        previous_close = self._float(quote.get("PreviousClose"))
        vwap = self._float(quote.get("VWAP"))
        net_change_pct = self._float(quote.get("NetChangePct"))

        score = 60
        bearish_score = 60
        reasons = []
        bearish_reasons = []

        if previous_close and last > previous_close:
            score += 14
            bearish_score -= 12
            reasons.append("ABOVE_PREVIOUS_CLOSE")
            bearish_reasons.append("ABOVE_PREVIOUS_CLOSE")
        else:
            score -= 12
            bearish_score += 14
            reasons.append("BELOW_PREVIOUS_CLOSE")
            bearish_reasons.append("BELOW_PREVIOUS_CLOSE")

        if vwap and last > vwap:
            score += 14
            bearish_score -= 12
            reasons.append("ABOVE_VWAP")
            bearish_reasons.append("ABOVE_VWAP")
        else:
            score -= 12
            bearish_score += 14
            reasons.append("BELOW_VWAP")
            bearish_reasons.append("BELOW_VWAP")

        day_range = high - low if high and low else 0
        close_location = 0.5

        if day_range > 0:
            close_location = (last - low) / day_range

        if close_location >= 0.70:
            score += 12
            bearish_score -= 12
            reasons.append("CLOSE_IN_UPPER_RANGE")
            bearish_reasons.append("CLOSE_IN_UPPER_RANGE")
        elif close_location <= 0.30:
            score -= 12
            bearish_score += 12
            reasons.append("CLOSE_IN_LOWER_RANGE")
            bearish_reasons.append("CLOSE_IN_LOWER_RANGE")

        if net_change_pct >= 2:
            score += 10
            bearish_score -= 10
            reasons.append("POSITIVE_MOMENTUM")
            bearish_reasons.append("POSITIVE_MOMENTUM")
        elif net_change_pct <= -2:
            score -= 10
            bearish_score += 10
            reasons.append("NEGATIVE_MOMENTUM")
            bearish_reasons.append("NEGATIVE_MOMENTUM")

        score = max(0, min(100, score))
        bearish_score = max(0, min(100, bearish_score))

        if score >= 85:
            trend_state = "ELITE_TREND_PERSISTENCE_LIVE"
        elif score >= 75:
            trend_state = "STRONG_TREND_PERSISTENCE_LIVE"
        elif score >= 60:
            trend_state = "DEVELOPING_TREND_LIVE"
        else:
            trend_state = "TREND_FAILURE_RISK_LIVE"

        if bearish_score >= 85:
            bearish_trend_state = "ELITE_BEARISH_TREND_PERSISTENCE_LIVE"
        elif bearish_score >= 75:
            bearish_trend_state = "STRONG_BEARISH_TREND_PERSISTENCE_LIVE"
        elif bearish_score >= 60:
            bearish_trend_state = "DEVELOPING_BEARISH_TREND_LIVE"
        else:
            bearish_trend_state = "BEARISH_TREND_FAILURE_RISK_LIVE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "trend_persistence_score": round(score, 2),
            "bearish_trend_persistence_score": round(bearish_score, 2),
            "trend_state": trend_state,
            "bearish_trend_state": bearish_trend_state,
            "trend_reasons": reasons,
            "bearish_trend_reasons": bearish_reasons,
            "trend_context": {
                "last": last,
                "high": high,
                "low": low,
                "previous_close": previous_close,
                "vwap": vwap,
                "net_change_pct": net_change_pct,
                "close_location": round(close_location, 4),
            },
            "execution_enabled": False,
            "status": "TREND_PERSISTENCE_SCORE_READY"
        }
