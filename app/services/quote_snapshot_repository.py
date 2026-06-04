import json
from datetime import datetime
from pathlib import Path


class QuoteSnapshotRepository:

    def __init__(self):
        self.storage_dir = Path("app/data/quote_snapshots")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, symbol, quote_data):
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        snapshot = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "quote_data": quote_data
        }

        filename = self.storage_dir / f"{symbol}_{timestamp}.json"

        filename.write_text(
            json.dumps(snapshot, indent=2)
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "file": str(filename),
            "execution_enabled": False,
            "status": "QUOTE_SNAPSHOT_SAVED"
        }
