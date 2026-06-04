from datetime import datetime

from app.services.market_universe_engine import MarketUniverseEngine
from app.services.quote_snapshot_service import QuoteSnapshotService


class UniverseSnapshotCaptureEngine:

    def capture_core_universe(self):
        universe = MarketUniverseEngine().get_universe()

        symbols = []

        for symbol_list in universe.get("universes", {}).values():
            for symbol in symbol_list:
                symbol = symbol.upper().strip()
                if symbol and symbol not in symbols:
                    symbols.append(symbol)

        captured = []

        for symbol in symbols:
            result = QuoteSnapshotService().capture_symbol_snapshot(symbol)

            captured.append({
                "symbol": symbol,
                "quote_status": result.get("quote_status"),
                "http_status": result.get("http_status"),
                "snapshot_saved": result.get("snapshot_saved"),
                "execution_enabled": False
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols_attempted": len(symbols),
            "symbols_captured": len([
                item for item in captured
                if item.get("snapshot_saved") is True
            ]),
            "results": captured,
            "execution_enabled": False,
            "status": "UNIVERSE_SNAPSHOT_CAPTURE_COMPLETE"
        }
