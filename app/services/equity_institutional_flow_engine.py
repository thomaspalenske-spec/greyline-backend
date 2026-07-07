from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
from app.services.institutional_footprint_engine import InstitutionalFootprintEngine


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

        footprint = InstitutionalFootprintEngine().evaluate(
            symbol=symbol,
            last=last,
            open_price=open_price,
            high=high,
            low=low,
            previous_close=previous_close,
            vwap=vwap,
            volume=volume,
            previous_volume=previous_volume,
            bid=bid,
            ask=ask,
            net_change_pct=net_change_pct,
            source="INFERRED_EQUITY_PROXY_NO_DIRECT_DARK_POOL_OR_BLOCK_FEED",
        )

        return footprint
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
