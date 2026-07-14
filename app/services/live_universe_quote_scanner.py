from datetime import datetime

from app.services.market_universe_engine import MarketUniverseEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class LiveUniverseQuoteScanner:

    @staticmethod
    def _extract_last(quote):
        """Pull the numeric Last price out of a TradeStation quote result, or None."""
        try:
            quotes = (quote.get("response_json") or {}).get("Quotes") or []
            last = float((quotes[0] if quotes else {}).get("Last") or 0)
            return last if last > 0 else None
        except (TypeError, ValueError, AttributeError, IndexError):
            return None

    def scan_safe_subset(self):
        universe = MarketUniverseEngine().get_universe()

        all_symbols = []

        for symbols in universe.get("universes", {}).values():
            for symbol in symbols:
                if symbol not in all_symbols:
                    all_symbols.append(symbol)

        safe_subset = all_symbols

        results = []

        for symbol in safe_subset:
            quote = TradeStationQuoteLiveEngine().get_quote(symbol)

            results.append({
                "symbol": symbol,
                "http_status": quote.get("http_status"),
                "quote_status": quote.get("status"),
                # Surface the last price already fetched in this quote so downstream
                # consumers (flow↔price co-record) don't have to make a second, redundant
                # live fetch that fails silently and leaves snapshots ungradable.
                "last": self._extract_last(quote),
                "execution_enabled": False
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols_requested": len(safe_subset),
            "symbols": results,
            "execution_enabled": False,
            "status": "LIVE_UNIVERSE_QUOTE_SCAN_COMPLETE"
        }
