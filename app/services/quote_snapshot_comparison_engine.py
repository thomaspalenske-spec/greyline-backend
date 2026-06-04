import json
from datetime import datetime
from pathlib import Path


class QuoteSnapshotComparisonEngine:

    def compare_latest_two(self, symbol):
        symbol = symbol.upper().strip()
        storage_dir = Path("app/data/quote_snapshots")

        files = sorted(
            storage_dir.glob(f"{symbol}_*.json"),
            reverse=True
        )

        if len(files) < 2:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "comparison_available": False,
                "snapshots_found": len(files),
                "execution_enabled": False,
                "status": "NOT_ENOUGH_SNAPSHOTS"
            }

        latest = json.loads(files[0].read_text())
        previous = json.loads(files[1].read_text())

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "comparison_available": True,
            "snapshots_found": len(files),
            "latest_snapshot_file": str(files[0]),
            "previous_snapshot_file": str(files[1]),
            "latest_timestamp": latest.get("timestamp"),
            "previous_timestamp": previous.get("timestamp"),
            "execution_enabled": False,
            "status": "QUOTE_SNAPSHOT_COMPARISON_READY"
        }
