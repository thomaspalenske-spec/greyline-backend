"""Protect the data that CANNOT be refetched — the single real redundancy gap.

GreyLine runs on one machine, one disk, one operator. Most of that is unfixable for a solo
operation and not worth pretending otherwise. But one piece is both critical and cheap to fix:
some of this data exists ONLY here, and if the disk dies it is gone permanently.

TIER 1 — UNRECOVERABLE (~5MB total). Accrues forward-only; no API can rebuild it:
  * options_reality/            the daily options surface panel. The ONLY evidence base the
                                options mission can ever be verified against, because option
                                history cannot be bought (UW's historic endpoint returns
                                nothing, TradeStation purges expired contracts). Losing it
                                restarts the edge experiment from zero.
  * research/universe_pit/      point-in-time universe membership + retained delisted names —
                                the survivorship-free record, which only exists going forward.
  * research/earnings_vol_panel implied moves recorded BEFORE each announcement. Unrecoverable
                                after the event by definition.
  * research/edge_hypothesis_registry  the record of every hypothesis tested. Losing the nulls
                                would make future results dishonest by omission.
  * the paper ledgers           the audit trail of what was actually booked.
  * lineage manifest            the fingerprint baseline; without it, silent retroactive
                                changes to settled history become undetectable.

TIER 2 — EXPENSIVE BUT RECOVERABLE (~400MB): price history and earnings history. Refetchable
from TradeStation/UW over hours of API calls. Worth backing up, but losing it is a delay, not
a permanent loss.

DESTINATION MUST BE OFF-MACHINE. Copying to another folder on the same disk protects against a
bad script, not against the disk failing — which is the actual risk. Default target is iCloud
Drive because it syncs off the machine; override with GREYLINE_BACKUP_DIR (an external volume
works equally well). The engine reports plainly whether its destination is genuinely off-disk.
"""

import hashlib
import json
import os
import re
import shutil
import threading
from datetime import datetime
from os import getenv
from pathlib import Path


class DisasterRecoveryEngine:

    ROOT = Path("app/data")
    DEFAULT_DEST = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/GreyLineBackup"

    TIER1 = [
        "options_reality",
        "research/universe_pit",
        "research/earnings_vol_panel.jsonl",
        "research/edge_hypothesis_registry.jsonl",
        "research/pead_study.json",
        "research/survivorship_bias_report.json",
        "options_paper_trading/options_paper_trade_ledger.jsonl",
        "paper_trading/paper_trade_ledger.jsonl",
        "data_quality/price_bar_lineage_manifest.json",
        "momentum_reversal/rebalance_state.json",
    ]
    TIER2 = ["historical", "historical_total_return", "earnings"]

    MAX_SNAPSHOTS = 14

    def dest(self):
        d = getenv("GREYLINE_BACKUP_DIR", "")
        return Path(d) if d else self.DEFAULT_DEST

    @staticmethod
    def _hash_file(p):
        h = hashlib.sha256()
        try:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
        except Exception:
            return None
        return h.hexdigest()[:16]

    def _collect(self, rels):
        """Expand the configured paths into concrete files."""
        files = []
        for rel in rels:
            src = self.ROOT / rel
            if src.is_dir():
                for p in sorted(src.rglob("*")):
                    if p.is_file():
                        files.append((p, p.relative_to(self.ROOT)))
            elif src.is_file():
                files.append((src, src.relative_to(self.ROOT)))
        return files

    def _is_off_machine(self, dest):
        """Honest check: is the destination actually somewhere a disk failure wouldn't take?"""
        s = str(dest)
        if "com~apple~CloudDocs" in s or "Dropbox" in s or "Google Drive" in s:
            return True, "cloud-synced (off-machine)"
        if s.startswith("/Volumes/"):
            return True, "external volume"
        return False, ("SAME DISK as the primary data — protects against a bad script, NOT "
                       "against disk failure. Set GREYLINE_BACKUP_DIR to iCloud or an external "
                       "volume for real redundancy.")

    _DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    _lock = threading.Lock()      # class-level: only one backup runs at a time across cycles

    def _clean_staging(self, snaps_dir):
        """Remove abandoned .staging-* dirs from runs that were killed mid-copy."""
        try:
            for p in snaps_dir.glob(".staging-*"):
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass

    def backup(self, tier2=False, save=True):
        """ATOMIC + verified. Build the whole tree in a staging dir, verify every file by hash there,
        and ONLY THEN promote it into place with a rename and advance the marker. An interrupted run
        (restart / sleep / crash) leaves at most an abandoned .staging-* dir — the previous complete
        snapshot, `latest`, and last_backup.json are never touched, so a partial can never be mistaken
        for progress and the marker never points at an incomplete backup."""
        dest = self.dest()
        off, off_note = self._is_off_machine(dest)
        rels = list(self.TIER1) + (list(self.TIER2) if tier2 else [])
        files = self._collect(rels)
        if not files:
            return {"status": "NOTHING_TO_BACK_UP", "backed_up": 0}

        day = datetime.utcnow().date().isoformat()
        snaps_dir = dest / "snapshots"
        snaps_dir.mkdir(parents=True, exist_ok=True)
        self._clean_staging(snaps_dir)
        staging = snaps_dir / f".staging-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"

        # stage every file and verify the COPY's hash against the source, in staging
        manifest, copied, total_bytes, errors, mismatched = {}, 0, 0, [], []
        for src, rel in files:
            try:
                target = staging / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                src_h = self._hash_file(src)
                if self._hash_file(target) != src_h or src_h is None:
                    mismatched.append(str(rel))
                    continue
                manifest[str(rel)] = {"sha256_16": src_h, "bytes": src.stat().st_size}
                total_bytes += src.stat().st_size
                copied += 1
            except Exception as e:
                errors.append({"file": str(rel), "error": str(e)[:80]})

        complete = bool(copied == len(files) and not mismatched and not errors)
        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "destination": str(dest), "off_machine": off, "destination_note": off_note,
            "tier2_included": bool(tier2), "files_backed_up": copied, "bytes": total_bytes,
            "verified_by_hash": copied, "mismatched": mismatched[:10], "errors": errors[:10],
            "snapshot": str(snaps_dir / day),
            "ok": complete,
            "status": "BACKUP_VERIFIED" if complete else "BACKUP_INCOMPLETE",
        }
        if not complete:
            shutil.rmtree(staging, ignore_errors=True)     # NEVER promote a partial
            return result                                  # marker untouched; last good stands

        # ATOMIC promote: replace any partial today-dir, then rename staging in. If killed between the
        # rmtree and the rename, today's dir is simply absent and the marker still points at the last
        # complete snapshot — recovery stays safe (never a partial masquerading as complete).
        dst = snaps_dir / day
        try:
            if dst.exists():
                shutil.rmtree(dst)
            os.rename(staging, dst)
        except Exception as e:
            shutil.rmtree(staging, ignore_errors=True)
            result["errors"].append({"promote": str(e)[:80]})
            result["ok"] = False
            result["status"] = "BACKUP_INCOMPLETE"
            return result
        result["snapshot"] = str(dst)

        if save:
            try:
                (dest / "backup_manifest.json").write_text(
                    json.dumps({"generated_at": result["timestamp"], "files": manifest}, indent=2))
                (self.ROOT / "data_quality").mkdir(parents=True, exist_ok=True)
                (self.ROOT / "data_quality" / "last_backup.json").write_text(json.dumps(result, indent=2))
            except Exception:
                pass

        # `latest` is a convenience mirror only — rebuilt AFTER the marker is safe, so an interrupted
        # rebuild can't hurt recovery (the marker already points at the complete dated snapshot).
        try:
            latest = dest / "latest"
            if latest.exists():
                shutil.rmtree(latest)
            shutil.copytree(dst, latest)
        except Exception:
            pass
        self._prune(dest)
        return result

    def _run_and_alert(self, tier2=False):
        """Worker body: run the atomic backup and SCREAM if it ends incomplete (moved off the
        scheduler so the alert fires from the async path, not the inline cycle)."""
        try:
            r = self.backup(tier2=tier2)
        except Exception as e:
            r = {"status": "BACKUP_DEGRADED", "error": repr(e)[:150]}
        if str(r.get("status")) in ("BACKUP_DEGRADED", "BACKUP_INCOMPLETE"):
            try:
                from app.services.operator_notification_engine import OperatorNotificationEngine
                OperatorNotificationEngine().record(
                    event_type="BACKUP_FAILED", title="Off-machine backup FAILED",
                    message=(f"Unrecoverable-data backup returned {r.get('status')}. Forward-only "
                             f"data is unprotected until this is fixed. {str(r.get('error') or '')[:150]}"),
                    severity="CRITICAL", source="DISASTER_RECOVERY", payload=r)
            except Exception:
                pass
        return r

    def backup_async(self, tier2=False):
        """Kick the backup OFF the scheduler's critical path. Non-blocking; one run at a time."""
        if not self._lock.acquire(blocking=False):
            return {"status": "BACKUP_ALREADY_RUNNING"}

        def _worker():
            try:
                self._run_and_alert(tier2=tier2)
            finally:
                self._lock.release()

        threading.Thread(target=_worker, name="greyline-backup", daemon=True).start()
        return {"status": "BACKUP_STARTED"}

    def _prune(self, dest):
        try:
            snaps = sorted(p for p in (dest / "snapshots").iterdir()
                           if p.is_dir() and self._DAY_RE.match(p.name))
            for old in snaps[:-self.MAX_SNAPSHOTS]:
                shutil.rmtree(old, ignore_errors=True)
        except Exception:
            pass

    def last_backup(self):
        try:
            return json.loads((self.ROOT / "data_quality" / "last_backup.json").read_text())
        except Exception:
            return None

    def _offmachine_file_count(self):
        """ACTUAL number of files sitting in the off-machine latest/ mirror right now — counted from
        disk, NOT read from the marker. The marker's claimed count once said 17 while latest/ held
        only 3 (a partial run), and every monitor believed it. Verify reality."""
        try:
            latest = self.dest() / "latest"
            if not latest.exists():
                return 0
            return sum(1 for p in latest.rglob("*") if p.is_file() and p.name != ".DS_Store")
        except Exception:
            return None

    def status(self):
        last = self.last_backup()
        dest = self.dest()
        off, note = self._is_off_machine(dest)
        unprotected = []
        if not last:
            unprotected = [str(r) for r in self.TIER1]
        age_h = None
        if last:
            try:
                age_h = round((datetime.utcnow()
                               - datetime.fromisoformat(last["timestamp"])).total_seconds() / 3600, 1)
            except Exception:
                pass
        # VERIFY reality vs the marker: expected = files that SHOULD be protected (current on-disk
        # TIER1 set); off_machine = what's ACTUALLY in latest/. Complete only if the mirror holds
        # them all. A shortfall means a partial/failed backup the marker is lying about.
        try:
            expected = len(self._collect(list(self.TIER1)))
        except Exception:
            expected = None
        off_files = self._offmachine_file_count()
        off_complete = bool(off and expected is not None and off_files is not None
                            and off_files >= expected)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "destination": str(dest), "off_machine": off, "destination_note": note,
            "last_backup_at": (last or {}).get("timestamp"),
            "hours_since_backup": age_h,
            "files_protected": (last or {}).get("files_backed_up", 0),   # marker's CLAIM
            "expected_files": expected,                                   # what SHOULD be protected
            "off_machine_files": off_files,                               # what IS off-machine (real)
            "off_machine_complete": off_complete,                         # verified, not trusted
            "verified": (last or {}).get("verified_by_hash", 0),
            "unprotected_unrecoverable_paths": unprotected,
            "why_it_matters": ("options_reality and the PIT/earnings panels accrue FORWARD ONLY "
                               "— no API can rebuild them. Losing the disk restarts the options "
                               "edge experiment from zero."),
            "status": "DISASTER_RECOVERY_STATUS",
        }

    STALE_MAX_AGE_H = 26.0        # a healthy 20h cadence + slack; older = a real gap
    STALE_THROTTLE_H = 6.0        # don't re-scream more than this often while stale
    STALE_MARKER = ROOT / "data_quality" / "backup_stale_alert.json"

    def alert_if_stale(self, now=None):
        """Scream when the last VERIFIED backup is too old — even if NO backup() call errored.

        Closes the silent hole: a backup killed mid-run (restart / sleep / crash) leaves a partial
        snapshot and never advances the marker, so the returned-status alert never fires. This checks
        the MARKER age directly. Throttled so a persistent gap warns periodically, not every cycle."""
        last = self.last_backup()
        now = now or datetime.utcnow()
        age_h = None
        if last:
            try:
                age_h = (now - datetime.fromisoformat(last["timestamp"])).total_seconds() / 3600.0
            except Exception:
                age_h = None
        stale = (last is None) or (age_h is not None and age_h > self.STALE_MAX_AGE_H)
        if not stale:
            return {"status": "BACKUP_FRESH", "hours_since_backup": round(age_h, 1) if age_h else None}

        # GIT-CHANNEL AWARENESS: the FILESYSTEM snapshot is only ONE of two off-machine channels, and it
        # is the one macOS TCC blocks / that a restart-mid-run leaves stale. The unrecoverable data is
        # ALSO pushed off-machine to a git remote (GitDataBackupEngine) — the channel the service can
        # actually rely on. If THAT is current, the data is NOT "at risk": screaming CRITICAL then cries
        # wolf on a benign state (exactly the false-alarm the operator hit). So: CRITICAL only when BOTH
        # channels are stale; if git is fresh, downgrade to a WARNING that the secondary/local snapshot
        # lagged (data still protected). Fail-SAFE: if git freshness can't be confirmed, treat it as NOT
        # fresh and alert as before — better to over-warn than miss a real double gap.
        git_h = None
        try:
            from app.services.git_data_backup_engine import GitDataBackupEngine
            git_h = GitDataBackupEngine().hours_since()
        except Exception:
            git_h = None
        git_fresh = (git_h is not None and git_h <= self.STALE_MAX_AGE_H)

        # throttle: only re-alert every STALE_THROTTLE_H
        try:
            prev = json.loads(self.STALE_MARKER.read_text()).get("alerted_at")
            if prev and (now - datetime.fromisoformat(prev)).total_seconds() < self.STALE_THROTTLE_H * 3600:
                return {"status": "BACKUP_STALE_THROTTLED",
                        "hours_since_backup": round(age_h, 1) if age_h else None,
                        "git_hours_since": round(git_h, 1) if git_h is not None else None}
        except Exception:
            pass
        try:
            from app.services.operator_notification_engine import OperatorNotificationEngine
            if git_fresh:
                # data IS protected off-machine via git — this is a redundancy note, not a data-at-risk alarm
                OperatorNotificationEngine().record(
                    event_type="BACKUP_FS_STALE_GIT_OK",
                    title="Local backup snapshot lagging (data still protected off-machine)",
                    message=(f"The filesystem snapshot is {round(age_h, 1) if age_h else 'never'}h old "
                             f"(threshold {self.STALE_MAX_AGE_H}h) — usually a restart/sleep interrupting "
                             f"it mid-run. NOT a data-loss risk: the primary off-machine git backup is "
                             f"current ({round(git_h, 1)}h ago), so the unrecoverable data IS protected. "
                             f"Local snapshot redundancy is reduced until the next uninterrupted cycle."),
                    severity="WARNING", source="DISASTER_RECOVERY",
                    payload={"hours_since_backup": age_h, "git_hours_since": git_h,
                             "last_backup_at": (last or {}).get("timestamp")})
            else:
                # BOTH channels stale (or git unconfirmable) — the genuine data-at-risk CRITICAL
                git_txt = (f"the git off-machine backup is ALSO stale ({round(git_h, 1)}h ago)"
                           if git_h is not None else "the git off-machine backup could not be confirmed")
                OperatorNotificationEngine().record(
                    event_type="BACKUP_STALE",
                    title="Off-machine backup is STALE",
                    message=(f"Last verified filesystem backup was {round(age_h, 1) if age_h else 'never'}h "
                             f"ago (threshold {self.STALE_MAX_AGE_H}h) and {git_txt}. Forward-only "
                             f"unrecoverable data (options surface, PIT archive, earnings panel) is at risk "
                             f"until a backup completes — likely interrupted mid-run by a restart/sleep."),
                    severity="CRITICAL", source="DISASTER_RECOVERY",
                    payload={"hours_since_backup": age_h, "git_hours_since": git_h,
                             "last_backup_at": (last or {}).get("timestamp")})
        except Exception:
            pass
        try:
            self.STALE_MARKER.parent.mkdir(parents=True, exist_ok=True)
            self.STALE_MARKER.write_text(json.dumps({"alerted_at": now.isoformat(),
                                                     "hours_since_backup": age_h}))
        except Exception:
            pass
        return {"status": "BACKUP_STALE_ALERTED", "hours_since_backup": round(age_h, 1) if age_h else None}
