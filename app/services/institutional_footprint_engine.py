from datetime import datetime
from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
from app.services.institutional_flow_memory_engine import InstitutionalFlowMemoryEngine


class InstitutionalFootprintEngine:

    def __init__(self):
        import os

        if os.getenv("GREYLINE_DISABLE_LIVE_UW", "").lower() in ["1", "true", "yes"]:
            self.uw = None
            return

        try:
            self.uw = UnusualWhalesProvider()
        except Exception:
            self.uw = None
    """
    Shared institutional footprint model.

    Works with live quote data or historical OHLCV bars.
    Missing fields are treated neutrally, not punitively.
    """

    def _float(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def evaluate(
        self,
        symbol,
        last=None,
        open_price=None,
        high=None,
        low=None,
        previous_close=None,
        vwap=None,
        volume=None,
        previous_volume=None,
        bid=None,
        ask=None,
        net_change_pct=None,
        source="INSTITUTIONAL_FOOTPRINT_ENGINE",
        allow_live_uw=False,
    ):

        live_flow = None
        live_darkpool = None

        if self.uw and allow_live_uw:
            try:
                live_flow = self.uw.recent_flow(symbol)
            except Exception as e:
                print("UW ERROR:", repr(e))

            try:
                live_darkpool = self.uw.dark_pool(symbol)
            except Exception as e:
                print("UW ERROR:", repr(e))

            try:
                memory = (
                    InstitutionalFlowMemoryEngine()
                )

                options_memory = (
                    memory.capture_options_flow(
                        live_flow,
                        symbol=symbol,
                    )
                )

                dark_pool_memory = (
                    memory.capture_dark_pool(
                        live_darkpool,
                        symbol=symbol,
                    )
                )
            except Exception:
                options_memory = None
                dark_pool_memory = None
        else:
            options_memory = None
            dark_pool_memory = None

        symbol = (symbol or "").upper().strip()

        last = self._float(last)
        open_price = self._float(open_price)
        high = self._float(high)
        low = self._float(low)
        previous_close = self._float(previous_close)
        vwap = self._float(vwap)
        volume = self._float(volume)
        previous_volume = self._float(previous_volume)
        bid = self._float(bid)
        ask = self._float(ask)

        if net_change_pct is None and last and previous_close:
            net_change_pct = ((last - previous_close) / previous_close) * 100
        net_change_pct = self._float(net_change_pct)

        inflow = 50
        outflow = 50
        reasons = []

        volume_ratio = volume / previous_volume if volume and previous_volume else 1.0
        spread_pct = ((ask - bid) / last) * 100 if last and bid and ask else 0.0
        intraday_range = high - low if high and low else 0
        close_location = ((last - low) / intraday_range) if intraday_range > 0 else 0.5

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

        if vwap > 0 and last > vwap:
            inflow += 18
            outflow -= 12
            reasons.append("BUYERS_ACCEPTING_ABOVE_VWAP")
        elif vwap > 0 and last < vwap:
            outflow += 18
            inflow -= 12
            reasons.append("SELLERS_ACCEPTING_BELOW_VWAP")
        else:
            reasons.append("VWAP_UNAVAILABLE_NEUTRAL")

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

        if net_change_pct >= 2 and volume_ratio >= 1.0:
            inflow += 8
            reasons.append("STRONG_UP_DAY_WITH_VOLUME")
        elif net_change_pct <= -2 and volume_ratio >= 1.0:
            outflow += 8
            reasons.append("STRONG_DOWN_DAY_WITH_VOLUME")

        if spread_pct and spread_pct <= 0.05:
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

        
        live_flow_score = None

        if live_flow:
            try:
                bullish = 0
                bearish = 0

                for trade in live_flow:
                    tags = [
                        str(t).lower()
                        for t in (trade.get("tags") or [])
                    ]

                    option_type = str(
                        trade.get("option_type") or ""
                    ).lower()

                    premium = float(
                        trade.get("premium") or 0
                    )

                    if "bullish" in tags or option_type == "call":
                        bullish += premium
                    elif "bearish" in tags or option_type == "put":
                        bearish += premium

                total = bullish + bearish

                if total > 0:
                    live_flow_score = round(
                        ((bullish - bearish) / total) * 100,
                        2,
                    )

                    if abs(live_flow_score) >= 15:
                        net = live_flow_score
                        confidence = min(100, round(abs(live_flow_score), 2))

                        if live_flow_score >= 15:
                            direction = "INFLOW"
                        elif live_flow_score <= -15:
                            direction = "OUTFLOW"
                        else:
                            direction = "NEUTRAL"

                        if confidence >= 30:
                            strength = "STRONG"
                        elif confidence >= 15:
                            strength = "DEVELOPING"
                        else:
                            strength = "WEAK"

                        reasons.append("UNUSUAL_WHALES_LIVE_FLOW_CONFIRMED")
            except Exception:
                pass

        direct_flow_feeds_connected = bool(
            (isinstance(live_flow, list) and live_flow)
            or (
                isinstance(live_darkpool, dict)
                and live_darkpool.get("data")
            )
        )

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
            "live_unusual_whales_flow_score": live_flow_score,
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
                "net_change_pct": round(net_change_pct, 4),
                "close_location": round(close_location, 4),
                "bid": bid,
                "ask": ask,
                "spread_pct": round(spread_pct, 4),
            },
            "flow_source": source,
            "direct_flow_feeds_connected": direct_flow_feeds_connected,
            "institutional_memory_capture": {
                "options_flow": options_memory,
                "dark_pool": dark_pool_memory,
            },
            "status": "INSTITUTIONAL_FOOTPRINT_READY",
        }
