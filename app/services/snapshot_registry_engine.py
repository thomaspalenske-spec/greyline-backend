from pathlib import Path


class SnapshotRegistryEngine:

    def list_snapshots(self):

        snapshot_dir = Path("app/snapshots")

        if not snapshot_dir.exists():
            return []

        return sorted(
            [f.name for f in snapshot_dir.glob("*.json")],
            reverse=True
        )
