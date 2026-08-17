"""The backup must be interruption-safe: an incomplete run can never corrupt the last good backup,
never advance the marker onto a partial, and never leave a partial masquerading as a real snapshot.
Plus the copy runs off the scheduler's critical path (async), one at a time."""

import shutil
import time

import pytest

from app.services import disaster_recovery_engine as M
from app.services.disaster_recovery_engine import DisasterRecoveryEngine


@pytest.fixture
def eng(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "options_reality").mkdir(parents=True)
    (root / "options_reality" / "s.jsonl").write_text('{"t":"NVDA"}\n')
    (root / "research").mkdir(parents=True)
    (root / "research" / "edge_hypothesis_registry.jsonl").write_text('{"n":"x"}\n')
    monkeypatch.setattr(DisasterRecoveryEngine, "ROOT", root)
    monkeypatch.setenv("GREYLINE_BACKUP_DIR", str(tmp_path / "dest"))
    return DisasterRecoveryEngine(), tmp_path


def test_incomplete_run_preserves_last_good_and_marker(eng, monkeypatch):
    e, tmp = eng
    good = e.backup()
    assert good["status"] == "BACKUP_VERIFIED"
    marker_before = (e.ROOT / "data_quality" / "last_backup.json").read_text()
    snap_before = sorted((tmp / "dest" / "snapshots").glob("*"))

    # now force every copy to fail mid-run -> INCOMPLETE
    monkeypatch.setattr(M.shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    r = e.backup()
    assert r["status"] == "BACKUP_INCOMPLETE" and r["ok"] is False
    # the previous good marker and snapshot are untouched
    assert (e.ROOT / "data_quality" / "last_backup.json").read_text() == marker_before
    assert sorted((tmp / "dest" / "snapshots").glob("*")) == snap_before


def test_no_staging_dir_leaks_after_success(eng):
    e, tmp = eng
    e.backup()
    assert list((tmp / "dest" / "snapshots").glob(".staging-*")) == []


def test_stale_staging_from_a_killed_run_is_cleaned(eng):
    e, tmp = eng
    snaps = tmp / "dest" / "snapshots"
    snaps.mkdir(parents=True)
    (snaps / ".staging-20260101T000000-999").mkdir()      # leftover from a killed run
    e.backup()
    assert list(snaps.glob(".staging-*")) == []


def test_partial_today_snapshot_is_replaced_by_complete(eng, monkeypatch):
    e, tmp = eng
    from datetime import datetime
    day = datetime.utcnow().date().isoformat()
    snaps = tmp / "dest" / "snapshots"
    (snaps / day / "options_reality").mkdir(parents=True)   # a PARTIAL today-dir (only one item)
    (snaps / day / "options_reality" / "s.jsonl").write_text("STALE PARTIAL")
    r = e.backup()
    assert r["status"] == "BACKUP_VERIFIED"
    # the complete tree replaced the partial (research file now present, content fresh)
    assert (snaps / day / "research" / "edge_hypothesis_registry.jsonl").exists()
    assert (snaps / day / "options_reality" / "s.jsonl").read_text() == '{"t":"NVDA"}\n'


def test_async_lock_prevents_concurrent_runs(eng):
    e, tmp = eng
    assert DisasterRecoveryEngine._lock.acquire(blocking=False)   # simulate a run in progress
    try:
        assert e.backup_async()["status"] == "BACKUP_ALREADY_RUNNING"
    finally:
        DisasterRecoveryEngine._lock.release()


def test_async_backup_completes_and_writes_marker(eng):
    e, tmp = eng
    assert e.backup_async()["status"] == "BACKUP_STARTED"
    for _ in range(50):                                          # poll up to ~2.5s for the worker
        if (e.ROOT / "data_quality" / "last_backup.json").exists():
            break
        time.sleep(0.05)
    assert e.last_backup()["status"] == "BACKUP_VERIFIED"
    assert not DisasterRecoveryEngine._lock.locked()             # lock released after completion
