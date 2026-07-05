from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class EquityInstitutionalFlowEngine:
    """
    Equity-specific inferred institutional flow detector.

    Uses currently available quote fields:
    - Volume vs previous volume
    - Price vs VWAP
    - Price vs previous close
    - Price vs open
    - Close location inside daily range
    - Spread quality

    Direct institutional feeds are not connected yet, so this is an inferred proxy.
    """

    def _float(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def evaluate_symbol(self, symbol):
        symbol = symbol.upper().strip()
        quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)

        if quote_result.get("http_status") != 200:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "institutional_inflow_score": 50,
                "institutional_outflow_score": 50,
                "net_institutional_flow_score": 0,
                "institutional_flow_direction": "UNKNOWN",
                "institutional_flow_confidence": 0,
                "institutional_flow_reasons": ["QUOTE_UNAVAILABLE"],
                "flow_source": "INFERRED_EQUITY_PROXY",
                "direct_flow_feeds_connected": False,
                "status": "EQUITY_INSTITUTIONAL_FLOW_DEGRADED",
            }

        quote = (quote_result.get("response_json") or {}).get("Quotes") or [{}]
        q = quote[0] if quote else {}

        last = self._float(q.get("Last"))
        open_price = self._float(q.get("Open"))
        high = self._float(q.get("High"))
        low = self._float(q.get("Low"))
        previous_close = self._float(q.get("PreviousClose"))
        vwap = self._float(q.get("VWAP"))
        volume = self._float(q.get("Volume"))
        previous_volume = self._float(q.get("PreviousVolume"))
        bid = self._float(q.get("Bid"))
        ask = self._float(q.get("Ask"))
        net_change_pct = self._float(q.get("NetChangePct"))

        inflow = 50
        outflow = 50
        reasons = []

        volume_ratio = volume / previous_volume if volume and previous_volume else 1.0
        spread_pct = ((ask - bid) / last) * 100 if last and bid and ask else 0.0
        intraday_range = high - low if high and low else 0
        close_location = ((last - low) / intraday_range) if intraday_range > 0 else 0.5

        # Volume participation: institutions leave footprints through participation.
        if volume_ratio >= 1.5:
            inflow += 14
            outflow += 14
            reasons.append("HEAVY_VOLUME_PARTICIPATION")
        elif volume_ratio >= 1.0:
            inflow += 8
            outflow += 8
            reasons.append("ABOVE_BASELINE_VOLUME")
        elif volume_ratio <= 0.6:
            inflow -= 8
            outflow -= 8
            reasons.append("WEAK_VOLUME_PARTICIPATION")

        # Directional price acceptance relative to VWAP.
        if vwap and last > vwap:
            inflow += 18
            outflow -= 12
            reasons.append("BUYERS_ACCEPTING_ABOVE_VWAP")
        elif vwap and last < vwap:
            outflow += 18
            inflow -= 12
            reasons.append("SELLERS_ACCEPTING_BELOW_VWAP")

        # Directional acceptance vs prior close and open.
        if previous_close and last > previous_close:
            inflow += 10
            outflow -= 7
            reasons.append("ABOVE_PREVIOUS_CLOSE")
        elif previous_close and last < previous_close:
            outflow += 10
            inflow -= 7
            reasons.append("BELOW_PREVIOUS_CLOSE")

        if open_price and last > open_price:
            inflow += 7
            outflow -= 5
            reasons.append("ABOVE_OPEN")
        elif open_price and last < open_price:
            outflow += 7
            inflow -= 5
            reasons.append("BELOW_OPEN")

        # Close location reveals accumulation/distribution pressure.
        if close_location >= 0.8:
            inflow += 13
            outflow -= 8
            reasons.append("CLOSING_NEAR_SESSION_HIGH")
        elif close_location <= 0.2:
            outflow += 13
            inflow -= 8
            reasons.append("CLOSING_NEAR_SESSION_LOW")
        elif close_location >= 0.65:
            inflow += 6
            reasons.append("UPPER_RANGE_ACCEPTANCE")
        elif close_location <= 0.35:
            outflow += 6
            reasons.append("LOWER_RANGE_ACCEPTANCE")

        # Large directional candles with volume get extra institutional weight.
        if net_change_pct >= 2 and volume_ratio >= 1.0:
            inflow += 8
            reasons.append("STRONG_UP_DAY_WITH_VOLUME")
        elif net_change_pct <= -2 and volume_ratio >= 1.0:
            outflow += 8
            reasons.append("STRONG_DOWN_DAY_WITH_VOLUME")

        # Wide spreads reduce confidence; tight spreads confirm tradability.
        if spread_pct <= 0.05 and last:
            inflow += 3
            outflow += 3
            reasons.append("TIGHT_SPREAD_CONFIRMS_LIQUIDITY")
        elif spread_pct >= 0.20:
            inflow -= 6
            outflow -= 6
            reasons.append("WIDE_SPREAD_REDUCES_CONFIDENCE")

        inflow = round(max(0, min(100, inflow)), 2)
        outflow = round(max(0, min(100, outflow)), 2)
        net = round(inflow - outflow, 2)
        confidence = round(abs(net), 2)

        if net >= 12:
            direction = "INFLOW"
        elif net <= -12:
            direction = "OUTFLOW"
        else:
            direction = "NEUTRAL"

        if confidence >= 30:
            strength = "STRONG"
        elif confidence >= 15:
            strength = "DEVELOPING"
        else:
            strength = "WEAK"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "institutional_inflow_score": inflow,
            "institutional_outflow_score": outflow,
            "net_institutional_flow_score": net,
            "institutional_flow_direction": direction,
            "institutional_flow_strength": strength,
            "institutional_flow_confidence": confidence,
            "institutional_flow_reasons": reasons,
            "institutional_flow_context": {
                "last": last,
                "open": open_price,
                "high": high,
                "low": low,
                "previous_close": previous_close,
                "vwap": vwap,
                "volume": volume,
                "previous_volume": previous_volume,
                "volume_ratio": round(volume_ratio, 4),
                "net_change_pct": net_change_pct,
                "close_location": round(close_location, 4),
                "bid": bid,
                "ask": ask,
                "spread_pct": round(spread_pct, 4),
            },
            "flow_source": "INFERRED_EQUITY_PROXY_NO_DIRECT_DARK_POOL_OR_BLOCK_FEED",
            "direct_flow_feeds_connected": False,
            "status": "EQUITY_INSTITUTIONAL_FLOW_READY",
        }
