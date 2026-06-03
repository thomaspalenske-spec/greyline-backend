from datetime import datetime

from app.services.watchlist_engine import WatchlistEngine


class WatchlistReader:

    def read_watchlist(self):
        watchlist = WatchlistEngine().get_watchlist()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "watchlist_found": True,
            "symbol_count": watchlist.get("symbol_count", 0),
            "symbols": watchlist.get("watchlist", {}).get("symbols", []),
            "execution_enabled": False,
            "status": "WATCHLIST_READER_ACTIVE"
        }
