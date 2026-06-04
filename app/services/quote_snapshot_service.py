from datetime import datetime

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
from app.services.quote_snapshot_repository import QuoteSnapshotRepository


class QuoteSnapshotService:

    def capture_symbol_snapshot(self, symbol):
        quote = TradeStationQuoteLiveEngine().get_quote(symbol)
        repo = QuoteSnapshotRepository()

        saved = repo.save_snapshot(symbol.upper().strip(), quote)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol.upper().strip(),
            "quote_status": quote.get("status"),
            "http_status": quote.get("http_status"),
            "snapshot_saved": saved.get("status") == "QUOTE_SNAPSHOT_SAVED",
            "execution_enabled": False,
            "status": "QUOTE_SNAPSHOT_CAPTURED"
        }
