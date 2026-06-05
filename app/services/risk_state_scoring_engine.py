from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class RiskStateScoringEngine:

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
                "risk_state_score": 50,
                "risk_state": "QUOTE_UNAVAILABLE",
                "execution_enabled": False,
                "status": "RISK_STATE_SCORE_DEGRADED"
            }

        quotes = quote_result.get("response_json", {}).get("Quotes", [])
        quote = quotes[0] if quotes else {}

        last = self._float(quote.get("Last"))
        bid = self._float(quote.get("Bid"))
        ask = self._float(quote.get("Ask"))
        vwap = self._float(quote.get("VWAP"))
        net_change_pct = abs(self._float(quote.get("NetChangePct")))
        volume = self._float(quote.get("Volume"))
        previous_volume = self._float(quote.get("PreviousVolume"))

        market_flags = quote.get("MarketFlags", {}) or {}
        is_halted = market_flags.get("IsHalted") is True
        is_delayed = market_flags.get("IsDelayed") is True

        spread_pct = 0.0
        if bid > 0 and ask > 0:
            spread_pct = ((ask - bid) / last) * 100 if last else 0.0

        vwap_distance_pct = 0.0
        if vwap > 0 and last > 0:
            vwap_distance_pct = abs((last - vwap) / vwap) * 100

        score = 90
        risk_state = "NORMAL"

        if is_halted:
            score = 15
            risk_state = "HALTED"
        elif is_delayed:
            score = 45
            risk_state = "DATA_DELAY_RISK"
        else:
            if net_change_pct >= 5:
                score -= 25
            elif net_change_pct >= 3:
                score -= 15
            elif net_change_pct >= 2:
                score -= 8

            if vwap_distance_pct >= 4:
                score -= 15
            elif vwap_distance_pct >= 2:
                score -= 8

            if spread_pct >= 0.25:
                score -= 15
            elif spread_pct >= 0.10:
                score -= 8

            if previous_volume and volume < previous_volume * 0.35:
                score -= 8

            score = max(0, min(100, score))

            if score >= 85:
                risk_state = "NORMAL"
            elif score >= 70:
                risk_state = "ELEVATED"
            elif score >= 50:
                risk_state = "DEFENSIVE"
            else:
                risk_state = "STRESSED"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "risk_state_score": round(score, 2),
            "risk_state": risk_state,
            "last": last,
            "bid": bid,
            "ask": ask,
            "spread_pct": round(spread_pct, 4),
            "vwap": vwap,
            "vwap_distance_pct": round(vwap_distance_pct, 4),
            "net_change_pct_abs": net_change_pct,
            "volume": volume,
            "previous_volume": previous_volume,
            "execution_enabled": False,
            "status": "RISK_STATE_SCORE_READY"
        }
