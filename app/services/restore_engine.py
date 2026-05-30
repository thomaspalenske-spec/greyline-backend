import json
from pathlib import Path


class RestoreEngine:

    def restore_snapshot(self, snapshot_path):

        path = Path(snapshot_path)

        if not path.exists():
            return {
                "restored": False,
                "error": "Snapshot not found"
            }

        with open(path, "r") as f:
            data = json.load(f)

        return {
            "restored": True,
            "snapshot": data
        }
