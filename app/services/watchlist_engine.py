import json
from datetime import datetime
from pathlib import Path


class WatchlistEngine:

    def __init__(self):
        self.storage_dir = Path("app/data/watchlist")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.watchlist_file = self.storage_dir / "watchlist.json"

    def get_watchlist(self):
        if not self.watchlist_file.exists():
            default_watchlist = {
                "symbols": [],
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            self.watchlist_file.write_text(json.dumps(default_watchlist, indent=2))

        data = json.loads(self.watchlist_file.read_text())

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "watchlist": data,
            "symbol_count": len(data.get("symbols", [])),
            "execution_enabled": False,
            "status": "WATCHLIST_ACTIVE"
        }

    def add_symbol(self, symbol):
        symbol = symbol.upper().strip()

        data = self.get_watchlist().get("watchlist", {})
        symbols = data.get("symbols", [])

        if symbol and symbol not in symbols:
            symbols.append(symbol)

        data["symbols"] = symbols
        data["updated_at"] = datetime.utcnow().isoformat()

        self.watchlist_file.write_text(json.dumps(data, indent=2))

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol_added": symbol,
            "symbol_count": len(symbols),
            "execution_enabled": False,
            "status": "WATCHLIST_SYMBOL_ADDED"
        }
