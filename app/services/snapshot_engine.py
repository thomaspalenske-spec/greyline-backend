import json
from pathlib import Path
from datetime import datetime


class SnapshotEngine:

    def __init__(self):
        self.snapshot_dir = Path("app/snapshots")
        self.snapshot_dir.mkdir(exist_ok=True)

    def create_snapshot(self, data):

        timestamp = datetime.utcnow().strftime(
            "%Y%m%d_%H%M%S"
        )

        filename = (
            self.snapshot_dir /
            f"snapshot_{timestamp}.json"
        )

        with open(filename, "w") as f:
            json.dump(data, f, indent=4)

        return str(filename)
