import json
from datetime import datetime
from pathlib import Path


class PortfolioRepository:

    def __init__(self):
        self.storage_dir = Path("app/data/portfolio")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_path = self.storage_dir / "latest_portfolio_snapshot.json"

    def save_snapshot(self, snapshot):
        payload = {
            "saved_at": datetime.utcnow().isoformat(),
            "snapshot": snapshot
        }

        self.snapshot_path.write_text(
            json.dumps(payload, indent=2)
        )

        return {
            "saved": True,
            "file": str(self.snapshot_path),
            "status": "PORTFOLIO_SNAPSHOT_SAVED"
        }

    def load_latest_snapshot(self):
        if not self.snapshot_path.exists():
            return {
                "found": False,
                "snapshot": None,
                "status": "NO_PORTFOLIO_SNAPSHOT_FOUND"
            }

        return {
            "found": True,
            "data": json.loads(self.snapshot_path.read_text()),
            "status": "PORTFOLIO_SNAPSHOT_LOADED"
        }
