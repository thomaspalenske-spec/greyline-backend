import json
from pathlib import Path


class PaperAccountSnapshotRepository:

    def __init__(self):
        self.path = Path(
            "app/data/paper_account_snapshots.json"
        )

        if not self.path.exists():
            self.path.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            self.path.write_text(
                json.dumps(
                    {
                        "snapshots": []
                    },
                    indent=4
                )
            )

    def load(self):
        with open(self.path, "r") as f:
            return json.load(f)

    def save(self, data):
        with open(self.path, "w") as f:
            json.dump(
                data,
                f,
                indent=4
            )

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
