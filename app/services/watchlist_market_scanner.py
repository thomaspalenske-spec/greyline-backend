from datetime import datetime

from app.services.watchlist_reader import WatchlistReader


class WatchlistMarketScanner:

    def scan(self):
        watchlist = WatchlistReader().read_watchlist()

        symbols = watchlist.get("symbols", [])

        scanned_symbols = []

        for symbol in symbols:
            scanned_symbols.append({
                "symbol": symbol,
                "market_data_connected": False,
                "status": "WAITING_FOR_MARKET_DATA"
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol_count": len(scanned_symbols),
            "symbols": scanned_symbols,
            "execution_enabled": False,
            "status": "WATCHLIST_SCAN_COMPLETE"
        }
