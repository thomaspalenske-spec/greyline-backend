"""Backup must be verified and OFF-MACHINE. An unverified backup is not a backup, and a
same-disk copy is not redundancy — it protects against a bad script, not a dead disk."""

import json

import pytest

from app.services.disaster_recovery_engine import DisasterRecoveryEngine


@pytest.fixture
def eng(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "options_reality").mkdir(parents=True)
    (root / "options_reality" / "options_surface_2026-07-24.jsonl").write_text('{"ticker":"NVDA"}\n')
    (root / "research").mkdir(parents=True)
    (root / "research" / "edge_hypothesis_registry.jsonl").write_text('{"name":"x"}\n')
    monkeypatch.setattr(DisasterRecoveryEngine, "ROOT", root)
    monkeypatch.setenv("GREYLINE_BACKUP_DIR", str(tmp_path / "dest"))
    return DisasterRecoveryEngine(), tmp_path


def test_backup_copies_and_verifies_by_hash(eng):
    e, tmp = eng
    r = e.backup()
    assert r["status"] == "BACKUP_VERIFIED"
    assert r["files_backed_up"] >= 2
    assert r["verified_by_hash"] == r["files_backed_up"]
    assert r["mismatched"] == []
    # the actual bytes landed
    assert (tmp / "dest" / "latest" / "options_reality" / "options_surface_2026-07-24.jsonl").exists()


def test_same_disk_destination_is_reported_as_not_redundancy(eng, monkeypatch):
    """THE honest check. Copying beside the original is not protection from disk failure."""
    e, tmp = eng
    monkeypatch.setenv("GREYLINE_BACKUP_DIR", str(tmp / "beside"))
    r = e.backup()
    assert r["off_machine"] is False
    assert "SAME DISK" in r["destination_note"]


def test_icloud_destination_counts_as_off_machine(eng, monkeypatch):
    e, tmp = eng
    monkeypatch.setenv("GREYLINE_BACKUP_DIR",
                       "/Users/x/Library/Mobile Documents/com~apple~CloudDocs/GreyLineBackup")
    off, note = e._is_off_machine(e.dest())
    assert off is True and "off-machine" in note


def test_dated_snapshot_is_kept_alongside_latest(eng):
    """A mirror alone propagates corruption. Dated snapshots preserve a good copy."""
    e, tmp = eng
    r = e.backup()
    assert (tmp / "dest" / "snapshots").exists()
    snaps = list((tmp / "dest" / "snapshots").iterdir())
    assert snaps, "no dated snapshot written"


def test_status_names_the_unrecoverable_stakes(eng):
    e, tmp = eng
    e.backup()
    s = e.status()
    assert s["files_protected"] >= 2
    assert "forward" in s["why_it_matters"].lower()
