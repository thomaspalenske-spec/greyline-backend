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

    _CHUNK = 100     # TS quote URLs are comma-lists with a length cap; ~100/call mirrors _bulk_quotes

    def scan_safe_subset(self):
        universe = MarketUniverseEngine().get_universe()

        all_symbols = []

        for symbols in universe.get("universes", {}).values():
            for symbol in symbols:
                if symbol not in all_symbols:
                    all_symbols.append(symbol)

        # BATCHED: was one serial get_quote per symbol across the ENTIRE universe (hundreds of throttle-bound
        # round-trips). Now ceil(N/100) batched get_quotes calls; each symbol's row is read from the result.
        engine = TradeStationQuoteLiveEngine()
        quotes = {}
        for i in range(0, len(all_symbols), self._CHUNK):
            quotes.update(engine.get_quotes(all_symbols[i:i + self._CHUNK]) or {})

        results = []
        for symbol in all_symbols:
            quote = quotes.get(str(symbol).upper()) or quotes.get(symbol) or {}
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
            "symbols_requested": len(all_symbols),
            "symbols": results,
            "execution_enabled": False,
            "status": "LIVE_UNIVERSE_QUOTE_SCAN_COMPLETE"
        }
