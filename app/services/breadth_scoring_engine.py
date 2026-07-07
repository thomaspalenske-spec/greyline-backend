from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class BreadthScoringEngine:
    _quote_context_cache = {}

    def _float(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _quote_context(self, symbol):
        symbol = symbol.upper().strip()
        if symbol in self._quote_context_cache:
            return dict(self._quote_context_cache[symbol])

        result = TradeStationQuoteLiveEngine().get_quote(symbol)

        if result.get("http_status") != 200:
            context = {
                "symbol": symbol,
                "available": False
            }
            self._quote_context_cache[symbol] = dict(context)
            return context

        quotes = result.get("response_json", {}).get("Quotes", [])
        quote = quotes[0] if quotes else {}

        last = self._float(quote.get("Last"))
        previous_close = self._float(quote.get("PreviousClose"))
        vwap = self._float(quote.get("VWAP"))
        net_change_pct = self._float(quote.get("NetChangePct"))
        volume = self._float(quote.get("Volume"))
        previous_volume = self._float(quote.get("PreviousVolume"))

        above_previous_close = bool(previous_close and last > previous_close)
        vwap_available = vwap > 0
        above_vwap = bool(vwap_available and last > vwap)

        # Intraday volume should not be compared harshly against full prior-day volume.
        # Treat volume as neutral unless it is meaningfully confirming.
        volume_confirming = bool(previous_volume and volume >= previous_volume * 0.7)
        volume_available = bool(previous_volume and volume)

        context = {
            "symbol": symbol,
            "available": True,
            "last": last,
            "previous_close": previous_close,
            "vwap": vwap,
            "net_change_pct": net_change_pct,
            "volume": volume,
            "previous_volume": previous_volume,
            "above_previous_close": above_previous_close,
            "above_vwap": above_vwap,
            "vwap_available": vwap_available,
            "volume_confirming": volume_confirming,
            "volume_available": volume_available
        }
        self._quote_context_cache[symbol] = dict(context)
        return context

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()

        spy = self._quote_context("SPY")
        qqq = self._quote_context("QQQ")

        score = 50
        bearish_score = 50
        reasons = []
        bearish_reasons = []

        for context in [spy, qqq]:
            label = context.get("symbol")

            if not context.get("available"):
                reasons.append(f"{label}_QUOTE_UNAVAILABLE")
                score -= 10
                continue

            if context.get("above_previous_close"):
                score += 12
                bearish_score -= 10
                reasons.append(f"{label}_ABOVE_PREVIOUS_CLOSE")
                bearish_reasons.append(f"{label}_ABOVE_PREVIOUS_CLOSE")
            else:
                score -= 10
                bearish_score += 12
                reasons.append(f"{label}_BELOW_PREVIOUS_CLOSE")
                bearish_reasons.append(f"{label}_BELOW_PREVIOUS_CLOSE")

            if context.get("vwap_available"):
                if context.get("above_vwap"):
                    score += 10
                    bearish_score -= 8
                    reasons.append(f"{label}_ABOVE_VWAP")
                    bearish_reasons.append(f"{label}_ABOVE_VWAP")
                else:
                    score -= 8
                    bearish_score += 10
                    reasons.append(f"{label}_BELOW_VWAP")
                    bearish_reasons.append(f"{label}_BELOW_VWAP")
            else:
                reasons.append(f"{label}_VWAP_UNAVAILABLE_NEUTRAL")
                bearish_reasons.append(f"{label}_VWAP_UNAVAILABLE_NEUTRAL")

            if context.get("net_change_pct", 0) <= -2:
                score -= 8
                bearish_score += 8
                reasons.append(f"{label}_NEGATIVE_MOMENTUM")
                bearish_reasons.append(f"{label}_NEGATIVE_MOMENTUM")
            elif context.get("net_change_pct", 0) >= 2:
                bearish_score -= 8
                bearish_reasons.append(f"{label}_POSITIVE_MOMENTUM")

            if context.get("volume_confirming"):
                score += 4
                bearish_score += 4
                reasons.append(f"{label}_VOLUME_CONFIRMING")
                bearish_reasons.append(f"{label}_VOLUME_CONFIRMING")
            else:
                reasons.append(f"{label}_VOLUME_NEUTRAL_INTRADAY")
                bearish_reasons.append(f"{label}_VOLUME_NEUTRAL_INTRADAY")

        score = max(0, min(100, score))
        bearish_score = max(0, min(100, bearish_score))

        if bearish_score >= 80:
            bearish_breadth_state = "BROAD_BEARISH_CONFIRMATION_LIVE"
        elif bearish_score >= 65:
            bearish_breadth_state = "MODERATE_BEARISH_CONFIRMATION_LIVE"
        elif bearish_score >= 45:
            bearish_breadth_state = "MIXED_BEARISH_BREADTH_LIVE"
        else:
            bearish_breadth_state = "BEARISH_BREADTH_WEAK_LIVE"

        if score >= 80:
            breadth_state = "BROAD_CONFIRMATION_LIVE"
        elif score >= 65:
            breadth_state = "MODERATE_CONFIRMATION_LIVE"
        elif score >= 45:
            breadth_state = "NARROW_OR_MIXED_LIVE"
        else:
            breadth_state = "BREADTH_WEAK_LIVE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "breadth_score": round(score, 2),
            "bearish_breadth_score": round(bearish_score, 2),
            "breadth_state": breadth_state,
            "bearish_breadth_state": bearish_breadth_state,
            "breadth_reasons": reasons,
            "bearish_breadth_reasons": bearish_reasons,
            "market_breadth_context": {
                "SPY": spy,
                "QQQ": qqq
            },
            "execution_enabled": False,
            "status": "BREADTH_SCORE_READY"
        }
