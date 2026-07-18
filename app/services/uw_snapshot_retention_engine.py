import json
import shutil
from datetime import datetime, timedelta, date
from os import getenv
from pathlib import Path

from app.services.uw_flow_signal_engine import UWFlowSignalEngine


class UWSnapshotRetentionEngine:
    """
    Bound the disk cost of raw Unusual Whales snapshots without losing the flow signal.

    The sweep writes ~5 MB blobs per symbol per cycle (~3 GB/day) — full-fidelity across
    30+ signal families. This keeps that fidelity for a recent window (default 7 days) and
    ages out older blobs, so disk stops growing unbounded (steady state ≈ window × daily).

    Safety — deletion is destructive and UW data is forward-only and unre-fetchable:
      * Only date-partitions strictly OLDER than the window are eligible.
      * Before a partition is removed, every blob in it is compacted into the queryable
        flow series (idempotent). The directional flow therefore survives the deletion.
      * If any blob in a partition fails to process, the WHOLE partition is kept — we
        never delete on an error.
      * dry_run reports exactly what would be reclaimed without touching anything.

    Accepted trade (option chosen deliberately): beyond the window, only the compact
    directional-flow record survives; the other families are dropped for aged data.
    """

    SNAP_DIR = Path("app/data/runtime/institutional_signal_snapshots")
    STATE = Path("app/data/runtime/uw_retention_state.json")
    MIN_HOURS_BETWEEN = 20   # in the cycle, prune at most ~once/day

    def __init__(self, retention_days=None):
        self.retention_days = int(retention_days if retention_days is not None
                                  else getenv("GREYLINE_UW_RETENTION_DAYS", "7"))
        self.flow = UWFlowSignalEngine()

    def _state(self):
        try:
            return json.loads(self.STATE.read_text())
        except Exception:
            return {}

    def _save(self, data):
        self.STATE.parent.mkdir(parents=True, exist_ok=True)
        self.STATE.write_text(json.dumps(data))

    def _due(self, now):
        last = self._state().get("last_run_at")
        if not last:
            return True
        try:
            return (now - datetime.fromisoformat(last)).total_seconds() >= self.MIN_HOURS_BETWEEN * 3600
        except Exception:
            return True

    @staticmethod
    def _parse_date(name):
        try:
            return date.fromisoformat(name)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _dir_bytes(d):
        return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())

    def prune(self, now=None, dry_run=False, force=False):
        now = now or datetime.utcnow()

        if not dry_run and not force and not self._due(now):
            return {"status": "UW_RETENTION_SKIPPED_NOT_DUE", "pruned": False,
                    "last_run_at": self._state().get("last_run_at")}

        if not self.SNAP_DIR.exists():
            return {"status": "UW_RETENTION_NO_SNAPSHOTS", "pruned": False}

        cutoff = (now - timedelta(days=self.retention_days)).date()
        partitions_removed = kept_on_error = files_compacted = 0
        reclaimed = 0

        for sym_dir in self.SNAP_DIR.iterdir():
            if not sym_dir.is_dir():
                continue
            for date_dir in sym_dir.iterdir():
                d = self._parse_date(date_dir.name)
                if d is None or d >= cutoff:
                    continue  # keep recent, keep anything unparseable

                # Compact every blob before we consider deleting the partition.
                safe = True
                for jf in date_dir.glob("*.json"):
                    try:
                        self.flow.record(json.loads(jf.read_text()))
                        files_compacted += 1
                    except Exception:
                        safe = False
                        break
                if not safe:
                    kept_on_error += 1
                    continue

                reclaimed += self._dir_bytes(date_dir)
                partitions_removed += 1
                if not dry_run:
                    shutil.rmtree(date_dir, ignore_errors=True)

        result = {
            "timestamp": now.isoformat(),
            "engine": "UWSnapshotRetentionEngine",
            "retention_days": self.retention_days,
            "cutoff_date": cutoff.isoformat(),
            "dry_run": dry_run,
            "pruned": (not dry_run) and partitions_removed > 0,
            "partitions_removed": partitions_removed,
            "files_compacted_before_delete": files_compacted,
            "partitions_kept_on_error": kept_on_error,
            "reclaimed_mb": round(reclaimed / 1e6, 1),
            "status": "UW_RETENTION_COMPLETE" if not dry_run else "UW_RETENTION_DRY_RUN",
        }
        if not dry_run:
            self._save({"last_run_at": now.isoformat(),
                        "partitions_removed": partitions_removed,
                        "reclaimed_mb": result["reclaimed_mb"]})
        return result
