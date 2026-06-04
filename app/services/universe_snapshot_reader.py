from datetime import datetime
from pathlib import Path


class UniverseSnapshotReader:

    def read_snapshot_coverage(self):
        storage_dir = Path("app/data/quote_snapshots")

        files = list(storage_dir.glob("*.json"))

        coverage = {}

        for file in files:
            symbol = file.name.split("_")[0]
            coverage[symbol] = coverage.get(symbol, 0) + 1

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol_count": len(coverage),
            "total_snapshots": len(files),
            "coverage": dict(sorted(coverage.items())),
            "execution_enabled": False,
            "status": "UNIVERSE_SNAPSHOT_COVERAGE_READY"
        }
