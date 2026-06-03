import json
from datetime import datetime
from pathlib import Path


class LivePortfolioSnapshotRepository:

    def __init__(self):
        self.storage_dir = Path("app/data/live_portfolio_snapshots")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, snapshot):
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        snapshot_file = self.storage_dir / f"live_portfolio_snapshot_{timestamp}.json"

        payload = {
            "saved_at": datetime.utcnow().isoformat(),
            "snapshot": snapshot,
            "execution_enabled": False
        }

        snapshot_file.write_text(json.dumps(payload, indent=2))

        latest_file = self.storage_dir / "latest_live_portfolio_snapshot.json"
        latest_file.write_text(json.dumps(payload, indent=2))

        return {
            "saved": True,
            "snapshot_file": str(snapshot_file),
            "latest_file": str(latest_file),
            "execution_enabled": False,
            "status": "LIVE_PORTFOLIO_SNAPSHOT_SAVED"
        }

    def load_latest_snapshot(self):
        latest_file = self.storage_dir / "latest_live_portfolio_snapshot.json"

        if not latest_file.exists():
            return {
                "found": False,
                "snapshot": None,
                "execution_enabled": False,
                "status": "NO_LIVE_PORTFOLIO_SNAPSHOT_FOUND"
            }

        return {
            "found": True,
            "data": json.loads(latest_file.read_text()),
            "execution_enabled": False,
            "status": "LIVE_PORTFOLIO_SNAPSHOT_LOADED"
        }
