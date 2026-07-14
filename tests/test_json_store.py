import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.persistence.json_store import atomic_write_json, read_json


def test_roundtrip(tmp_path):
    p = tmp_path / "sub" / "data.json"  # parent dir does not exist yet
    atomic_write_json(p, {"a": 1, "b": [1, 2, 3]})
    assert read_json(p) == {"a": 1, "b": [1, 2, 3]}


def test_write_is_atomic_no_temp_files_left(tmp_path):
    p = tmp_path / "data.json"
    atomic_write_json(p, {"x": 1})
    leftovers = [f.name for f in tmp_path.iterdir() if f.name != "data.json"]
    assert leftovers == []  # temp file was renamed away, nothing dangling


def test_missing_file_returns_default(tmp_path):
    p = tmp_path / "nope.json"
    assert read_json(p, default={"snapshots": []}) == {"snapshots": []}


def test_callable_default_yields_fresh_mutable(tmp_path):
    a = read_json(tmp_path / "a.json", default=list)
    b = read_json(tmp_path / "b.json", default=list)
    a.append(1)
    assert a == [1] and b == []  # distinct instances, not a shared default


def test_empty_file_returns_default(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("")
    assert read_json(p, default={"ok": True}) == {"ok": True}


def test_corrupt_file_is_backed_up_and_default_returned(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("{ this is not json ")
    result = read_json(p, default={"recovered": True})
    assert result == {"recovered": True}
    # corrupt content preserved for forensics, real path cleared
    assert (tmp_path / "corrupt.json.corrupt").exists()
    assert not p.exists()


def test_normalizer_applied(tmp_path):
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps([{"id": 1}]))  # legacy top-level list

    def norm(d):
        return {"items": d} if isinstance(d, list) else d

    assert read_json(p, normalizer=norm) == {"items": [{"id": 1}]}


def test_overwrite_replaces_content(tmp_path):
    p = tmp_path / "data.json"
    atomic_write_json(p, {"v": 1})
    atomic_write_json(p, {"v": 2})
    assert read_json(p) == {"v": 2}


# ---- adopters use the durable store correctly ----
def test_snapshot_repository_uses_durable_store(tmp_path, monkeypatch):
    import app.services.paper_account_snapshot_repository as repo_mod
    from app.services.paper_account_snapshot_repository import PaperAccountSnapshotRepository

    repo = PaperAccountSnapshotRepository()
    repo.path = tmp_path / "paper_account_snapshots.json"

    # fresh (missing) -> no crash, empty
    assert repo.get_snapshots() == []

    # legacy top-level list on disk -> normalized, no crash
    repo.path.write_text(json.dumps([{"equity": 100}]))
    assert repo.get_snapshots() == [{"equity": 100}]

    # append persists atomically and reloads
    repo.append_snapshot({"equity": 200})
    assert len(repo.get_snapshots()) == 2
