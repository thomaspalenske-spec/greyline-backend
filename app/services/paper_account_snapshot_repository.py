from pathlib import Path

from app.services.persistence.json_store import atomic_write_json, read_json


def _normalize_snapshots(data):
    # Tolerate a legacy/top-level list format (the file was found on disk as a bare
    # JSON array). Normalize to {"snapshots": [...]} so callers never crash with
    # 'list' object has no attribute 'get'.
    if isinstance(data, list):
        return {"snapshots": data}
    if not isinstance(data, dict):
        return {"snapshots": []}
    data.setdefault("snapshots", [])
    return data


class PaperAccountSnapshotRepository:

    def __init__(self):
        self.path = Path("app/data/paper_account_snapshots.json")

    def load(self):
        # Missing/empty/corrupt file -> {"snapshots": []} (self-healing, no crash).
        return read_json(
            self.path,
            default=lambda: {"snapshots": []},
            normalizer=_normalize_snapshots,
        )

    def save(self, data):
        atomic_write_json(self.path, data, indent=4)

    def append_snapshot(
        self,
        snapshot
    ):
        data = self.load()

        data["snapshots"].append(
            snapshot
        )

        self.save(data)

        return {
            "snapshot_saved": True,
            "snapshot_count": len(
                data["snapshots"]
            ),
            "status": "SNAPSHOT_SAVED"
        }

    def get_snapshots(self):
        return self.load().get(
            "snapshots",
            []
        )
