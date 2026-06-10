import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.snapshot_integrity_engine import SnapshotIntegrityEngine


def test_valid_snapshot_passes_integrity(tmp_path):
    snapshot = {
        "timestamp": "2026-06-10T00:00:00",
        "account_id": None,
        "cash_balance": 0.0,
        "buying_power": 0.0,
        "equity": 0.0,
        "positions": [],
        "open_orders": [],
        "source": "TEST",
        "broker_connected": False,
        "execution_enabled": False,
        "status": "TEST_SNAPSHOT"
    }

    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot))

    result = SnapshotIntegrityEngine().validate_snapshot(path)

    assert result["valid"] is True
    assert result["missing_fields"] == []


def test_snapshot_missing_required_fields_fails(tmp_path):
    path = tmp_path / "bad_snapshot.json"
    path.write_text(json.dumps({"timestamp": "2026-06-10T00:00:00"}))

    result = SnapshotIntegrityEngine().validate_snapshot(path)

    assert result["valid"] is False
    assert "equity" in result["missing_fields"]


def test_missing_snapshot_file_fails(tmp_path):
    result = SnapshotIntegrityEngine().validate_snapshot(tmp_path / "missing.json")

    assert result["valid"] is False
    assert result["error"] == "Snapshot file does not exist"
