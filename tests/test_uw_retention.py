import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.uw_snapshot_retention_engine import UWSnapshotRetentionEngine

NOW = datetime(2026, 7, 18, 12, 0, 0)


def _blob(with_flow=True):
    snap = {"symbol": "TEST", "timestamp": "2026-07-01T10:00:00+00:00", "providers": {}}
    if with_flow:
        snap["providers"] = {"UNUSUAL_WHALES": {"signals": {"flow_per_strike_intraday": {"data": [
            {"call_premium_ask_side": "1000", "put_premium_ask_side": "500", "net_premium": "500"},
        ]}}}}
    return snap


def _engine(tmp_path, retention_days=7):
    eng = UWSnapshotRetentionEngine(retention_days=retention_days)
    eng.SNAP_DIR = tmp_path / "snapshots"
    eng.STATE = tmp_path / "state.json"
    eng.flow.OUT_DIR = tmp_path / "uw_flow"
    return eng


def _write(eng, symbol, day, name, snap):
    d = eng.SNAP_DIR / symbol / day
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(snap))


def test_old_partition_is_pruned_after_compacting(tmp_path):
    eng = _engine(tmp_path)
    _write(eng, "TEST", "2026-07-01", "10-00-00-000000.json", _blob())  # 17 days old

    out = eng.prune(now=NOW, force=True)
    assert out["partitions_removed"] == 1
    assert out["files_compacted_before_delete"] == 1
    assert not (eng.SNAP_DIR / "TEST" / "2026-07-01").exists()   # blob gone
    # the directional flow survived into the compact series
    series = (eng.flow.OUT_DIR / "TEST.jsonl")
    assert series.exists() and "directional_flow" in series.read_text()


def test_recent_partition_is_kept(tmp_path):
    eng = _engine(tmp_path)
    _write(eng, "TEST", "2026-07-16", "10-00-00-000000.json", _blob())  # 2 days old

    out = eng.prune(now=NOW, force=True)
    assert out["partitions_removed"] == 0
    assert (eng.SNAP_DIR / "TEST" / "2026-07-16").exists()


def test_uncompactable_partition_is_kept_not_deleted(tmp_path):
    # A corrupt blob must never be deleted — we don't lose data on an error.
    eng = _engine(tmp_path)
    d = eng.SNAP_DIR / "TEST" / "2026-07-01"
    d.mkdir(parents=True)
    (d / "bad.json").write_text("{ this is not valid json")

    out = eng.prune(now=NOW, force=True)
    assert out["partitions_removed"] == 0
    assert out["partitions_kept_on_error"] == 1
    assert d.exists()   # kept


def test_dry_run_reports_but_deletes_nothing(tmp_path):
    eng = _engine(tmp_path)
    _write(eng, "TEST", "2026-07-01", "10-00-00-000000.json", _blob())

    out = eng.prune(now=NOW, dry_run=True)
    assert out["dry_run"] is True
    assert out["partitions_removed"] == 1        # would remove
    assert out["pruned"] is False
    assert (eng.SNAP_DIR / "TEST" / "2026-07-01").exists()   # still there


def test_self_gates_to_once_per_window(tmp_path):
    eng = _engine(tmp_path)
    eng.STATE.parent.mkdir(parents=True, exist_ok=True)
    eng.STATE.write_text(json.dumps({"last_run_at": NOW.isoformat()}))
    out = eng.prune(now=NOW + timedelta(hours=1))   # not forced, ran recently
    assert out["status"] == "UW_RETENTION_SKIPPED_NOT_DUE"
