from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class InstitutionalSponsorshipScoringEngine:

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
                "institutional_sponsorship_score": 50,
                "institutional_sponsorship_state": "QUOTE_UNAVAILABLE",
                "execution_enabled": False,
                "status": "INSTITUTIONAL_SPONSORSHIP_SCORE_DEGRADED"
            }

        quote = (quote_result.get("response_json", {}).get("Quotes") or [{}])[0]

        last = self._float(quote.get("Last"))
        previous_close = self._float(quote.get("PreviousClose"))
        vwap = self._float(quote.get("VWAP"))
        volume = self._float(quote.get("Volume"))
        previous_volume = self._float(quote.get("PreviousVolume"))
        bid = self._float(quote.get("Bid"))
        ask = self._float(quote.get("Ask"))

        spread_pct = ((ask - bid) / last) * 100 if last and bid and ask else 0.0

        score = 60
        reasons = []

        if previous_volume and volume >= previous_volume:
            score += 18
            reasons.append("VOLUME_EXPANSION")
        elif previous_volume and volume >= previous_volume * 0.7:
            score += 8
            reasons.append("MODERATE_VOLUME_PARTICIPATION")
        else:
            score -= 10
            reasons.append("WEAK_VOLUME_PARTICIPATION")

        if vwap and last > vwap:
            score += 14
            reasons.append("PRICE_ABOVE_VWAP")
        else:
            score -= 12
            reasons.append("PRICE_BELOW_VWAP")

        if previous_close and last > previous_close:
            score += 12
            reasons.append("PRICE_ABOVE_PREVIOUS_CLOSE")
        else:
            score -= 10
            reasons.append("PRICE_BELOW_PREVIOUS_CLOSE")

        if spread_pct <= 0.05:
            score += 6
            reasons.append("TIGHT_SPREAD")
        elif spread_pct >= 0.20:
            score -= 8
            reasons.append("WIDE_SPREAD")

        score = max(0, min(100, score))

        if score >= 85:
            sponsorship_state = "ELITE_INSTITUTIONAL_SPONSORSHIP_LIVE"
        elif score >= 75:
            sponsorship_state = "STRONG_INSTITUTIONAL_SPONSORSHIP_LIVE"
        elif score >= 60:
            sponsorship_state = "DEVELOPING_INSTITUTIONAL_SPONSORSHIP_LIVE"
        else:
            sponsorship_state = "WEAK_INSTITUTIONAL_SPONSORSHIP_LIVE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "institutional_sponsorship_score": round(score, 2),
            "institutional_sponsorship_state": sponsorship_state,
            "institutional_sponsorship_reasons": reasons,
            "institutional_sponsorship_context": {
                "last": last,
                "previous_close": previous_close,
                "vwap": vwap,
                "volume": volume,
                "previous_volume": previous_volume,
                "bid": bid,
                "ask": ask,
                "spread_pct": round(spread_pct, 4),
            },
            "execution_enabled": False,
            "status": "INSTITUTIONAL_SPONSORSHIP_SCORE_READY"
        }
