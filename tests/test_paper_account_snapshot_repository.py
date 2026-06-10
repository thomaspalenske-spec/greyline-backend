import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_account_snapshot_repository import (
    PaperAccountSnapshotRepository
)


def test_append_snapshot(tmp_path):
    repo = PaperAccountSnapshotRepository()

    repo.path = tmp_path / "snapshots.json"
    repo.save({"snapshots": []})

    result = repo.append_snapshot(
        {
            "equity": 10000.0
        }
    )

    assert result["snapshot_saved"] is True
    assert result["snapshot_count"] == 1


def test_get_snapshots(tmp_path):
    repo = PaperAccountSnapshotRepository()

    repo.path = tmp_path / "snapshots.json"
    repo.save(
        {
            "snapshots": [
                {"equity": 10000.0},
                {"equity": 10100.0}
            ]
        }
    )

    snapshots = repo.get_snapshots()

    assert len(snapshots) == 2
    assert snapshots[0]["equity"] == 10000.0
    assert snapshots[1]["equity"] == 10100.0


def test_empty_repository_returns_empty_list(tmp_path):
    repo = PaperAccountSnapshotRepository()

    repo.path = tmp_path / "snapshots.json"
    repo.save({"snapshots": []})

    assert repo.get_snapshots() == []
