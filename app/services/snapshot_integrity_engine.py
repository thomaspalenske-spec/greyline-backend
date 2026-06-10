import json
from pathlib import Path


class SnapshotIntegrityEngine:

    REQUIRED_FIELDS = [
        "timestamp",
        "account_id",
        "cash_balance",
        "buying_power",
        "equity",
        "positions",
        "open_orders",
        "source",
        "broker_connected",
        "execution_enabled",
        "status"
    ]

    def validate_snapshot(self, snapshot_path):

        path = Path(snapshot_path)

        if not path.exists():
            return {
                "valid": False,
                "error": "Snapshot file does not exist"
            }

        try:
            with open(path, "r") as f:
                snapshot = json.load(f)

            missing_fields = [
                field
                for field in self.REQUIRED_FIELDS
                if field not in snapshot
            ]

            return {
                "valid": len(missing_fields) == 0,
                "missing_fields": missing_fields,
                "field_count": len(snapshot.keys()),
                "file": str(path),
                "error": None
            }

        except Exception as error:
            return {
                "valid": False,
                "error": str(error),
                "file": str(path)
            }
