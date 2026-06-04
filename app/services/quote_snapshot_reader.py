import json
from datetime import datetime
from pathlib import Path


class QuoteSnapshotReader:

    def read_latest_snapshot(self, symbol):
        symbol = symbol.upper().strip()

        storage_dir = Path("app/data/quote_snapshots")

        files = sorted(
            storage_dir.glob(f"{symbol}_*.json"),
            reverse=True
        )

        if not files:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "snapshot_found": False,
                "execution_enabled": False,
                "status": "NO_QUOTE_SNAPSHOT_FOUND"
            }

        latest_file = files[0]

        data = json.loads(
            latest_file.read_text()
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "snapshot_found": True,
            "snapshot": data,
            "execution_enabled": False,
            "status": "QUOTE_SNAPSHOT_READER_ACTIVE"
        }
