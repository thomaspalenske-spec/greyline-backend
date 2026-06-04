from datetime import datetime

from app.services.market_universe_engine import MarketUniverseEngine


class UniverseQuoteScanner:

    def scan_universe(self):
        universe = MarketUniverseEngine().get_universe()

        scanned = []

        for universe_name, symbols in universe.get("universes", {}).items():
            for symbol in symbols:
                scanned.append({
                    "universe": universe_name,
                    "symbol": symbol,
                    "quote_connected": False,
                    "status": "WAITING_FOR_QUOTE_ENGINE"
                })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols_scanned": len(scanned),
            "results": scanned,
            "execution_enabled": False,
            "status": "UNIVERSE_SCAN_COMPLETE"
        }
