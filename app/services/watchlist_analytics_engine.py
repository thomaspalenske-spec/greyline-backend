from datetime import datetime

from app.services.watchlist_reader import WatchlistReader


class WatchlistAnalyticsEngine:

    def analyze_watchlist(self):
        watchlist = WatchlistReader().read_watchlist()
        symbols = watchlist.get("symbols", [])

        duplicates = sorted(
            set([
                symbol for symbol in symbols
                if symbols.count(symbol) > 1
            ])
        )

        empty_symbols = [
            symbol for symbol in symbols
            if not symbol or not str(symbol).strip()
        ]

        integrity_ok = (
            watchlist.get("watchlist_found") is True
            and len(symbols) > 0
            and len(duplicates) == 0
            and len(empty_symbols) == 0
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol_count": len(symbols),
            "duplicates": duplicates,
            "empty_symbols": empty_symbols,
            "integrity_ok": integrity_ok,
            "execution_enabled": False,
            "status": "WATCHLIST_ANALYTICS_HEALTHY" if integrity_ok else "WATCHLIST_ANALYTICS_DEGRADED"
        }
