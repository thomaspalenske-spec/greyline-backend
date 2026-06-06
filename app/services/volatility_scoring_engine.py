from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class VolatilityScoringEngine:

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
                "volatility_score": 50,
                "volatility_state": "QUOTE_UNAVAILABLE",
                "execution_enabled": False,
                "status": "VOLATILITY_SCORE_DEGRADED"
            }

        quote = (quote_result.get("response_json", {}).get("Quotes") or [{}])[0]

        last = self._float(quote.get("Last"))
        high = self._float(quote.get("High"))
        low = self._float(quote.get("Low"))
        bid = self._float(quote.get("Bid"))
        ask = self._float(quote.get("Ask"))
        vwap = self._float(quote.get("VWAP"))
        net_change_pct = abs(self._float(quote.get("NetChangePct")))

        range_pct = ((high - low) / last) * 100 if last and high and low else 0.0
        spread_pct = ((ask - bid) / last) * 100 if last and bid and ask else 0.0
        vwap_distance_pct = abs((last - vwap) / vwap) * 100 if last and vwap else 0.0

        score = 90
        reasons = []

        if range_pct >= 6:
            score -= 30
            reasons.append("EXTREME_INTRADAY_RANGE")
        elif range_pct >= 4:
            score -= 20
            reasons.append("HIGH_INTRADAY_RANGE")
        elif range_pct >= 2.5:
            score -= 10
            reasons.append("MODERATE_INTRADAY_RANGE")
        else:
            reasons.append("CONTROLLED_INTRADAY_RANGE")

        if net_change_pct >= 5:
            score -= 25
            reasons.append("EXTREME_DAILY_MOVE")
        elif net_change_pct >= 3:
            score -= 15
            reasons.append("HIGH_DAILY_MOVE")
        elif net_change_pct >= 2:
            score -= 8
            reasons.append("MODERATE_DAILY_MOVE")

        if vwap_distance_pct >= 3:
            score -= 12
            reasons.append("EXTENDED_FROM_VWAP")
        elif vwap_distance_pct >= 1.5:
            score -= 6
            reasons.append("MODERATELY_EXTENDED_FROM_VWAP")

        if spread_pct >= 0.25:
            score -= 15
            reasons.append("WIDE_SPREAD")
        elif spread_pct >= 0.10:
            score -= 8
            reasons.append("MODERATE_SPREAD")
        else:
            reasons.append("TIGHT_SPREAD")

        score = max(0, min(100, score))

        if score >= 85:
            volatility_state = "CONTROLLED_VOLATILITY_LIVE"
        elif score >= 70:
            volatility_state = "ELEVATED_VOLATILITY_LIVE"
        elif score >= 50:
            volatility_state = "HIGH_VOLATILITY_LIVE"
        else:
            volatility_state = "EXTREME_VOLATILITY_LIVE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "volatility_score": round(score, 2),
            "volatility_state": volatility_state,
            "volatility_reasons": reasons,
            "volatility_context": {
                "last": last,
                "high": high,
                "low": low,
                "range_pct": round(range_pct, 4),
                "bid": bid,
                "ask": ask,
                "spread_pct": round(spread_pct, 4),
                "vwap": vwap,
                "vwap_distance_pct": round(vwap_distance_pct, 4),
                "net_change_pct_abs": net_change_pct,
            },
            "execution_enabled": False,
            "status": "VOLATILITY_SCORE_READY"
        }
