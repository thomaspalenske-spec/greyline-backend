import json
from pathlib import Path


class SnapshotIntegrityEngine:

    def validate_snapshot(self, snapshot_path):

        path = Path(snapshot_path)

        if not path.exists():
            return {
                "valid": False,
                "error": "Snapshot file does not exist"
            }

        try:
            with open(path, "r") as f:
                json.load(f)

            return {
                "valid": True,
                "error": None,
                "file": str(path)
            }

        except Exception as error:
            return {
                "valid": False,
                "error": str(error),
                "file": str(path)
            }
