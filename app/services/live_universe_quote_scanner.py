from datetime import datetime

from app.services.market_universe_engine import MarketUniverseEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class LiveUniverseQuoteScanner:

    def scan_safe_subset(self):
        universe = MarketUniverseEngine().get_universe()

        all_symbols = []

        for symbols in universe.get("universes", {}).values():
            for symbol in symbols:
                if symbol not in all_symbols:
                    all_symbols.append(symbol)

        safe_subset = all_symbols[:5]

        results = []

        for symbol in safe_subset:
            quote = TradeStationQuoteLiveEngine().get_quote(symbol)

            results.append({
                "symbol": symbol,
                "http_status": quote.get("http_status"),
                "quote_status": quote.get("status"),
                "execution_enabled": False
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols_requested": len(safe_subset),
            "symbols": results,
            "execution_enabled": False,
            "status": "LIVE_UNIVERSE_QUOTE_SCAN_COMPLETE"
        }
