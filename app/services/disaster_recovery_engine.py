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
import shutil
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

    def backup(self, tier2=False, save=True):
        dest = self.dest()
        off, off_note = self._is_off_machine(dest)
        rels = list(self.TIER1) + (list(self.TIER2) if tier2 else [])
        files = self._collect(rels)
        if not files:
            return {"status": "NOTHING_TO_BACK_UP", "backed_up": 0}

        day = datetime.utcnow().date().isoformat()
        latest = dest / "latest"
        snap = dest / "snapshots" / day
        manifest, copied, total_bytes, errors = {}, 0, 0, []

        for src, rel in files:
            try:
                for base in (latest, snap):
                    target = base / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
                manifest[str(rel)] = {"sha256_16": self._hash_file(src),
                                      "bytes": src.stat().st_size}
                total_bytes += src.stat().st_size
                copied += 1
            except Exception as e:
                errors.append({"file": str(rel), "error": str(e)[:80]})

        # VERIFY: a backup nobody verified is a backup nobody has.
        verified, mismatched = 0, []
        for rel, meta in manifest.items():
            t = latest / rel
            if self._hash_file(t) == meta["sha256_16"]:
                verified += 1
            else:
                mismatched.append(rel)

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "destination": str(dest),
            "off_machine": off, "destination_note": off_note,
            "tier2_included": bool(tier2),
            "files_backed_up": copied, "bytes": total_bytes,
            "verified_by_hash": verified, "mismatched": mismatched[:10],
            "errors": errors[:10],
            "snapshot": str(snap),
            "ok": bool(copied and not mismatched and not errors),
            "status": ("BACKUP_VERIFIED" if (copied and not mismatched and not errors)
                       else "BACKUP_INCOMPLETE"),
        }
        if save:
            try:
                (dest / "backup_manifest.json").write_text(
                    json.dumps({"generated_at": result["timestamp"], "files": manifest}, indent=2))
                (self.ROOT / "data_quality").mkdir(parents=True, exist_ok=True)
                (self.ROOT / "data_quality" / "last_backup.json").write_text(json.dumps(result, indent=2))
            except Exception:
                pass
        self._prune(dest)
        return result

    def _prune(self, dest):
        try:
            snaps = sorted((dest / "snapshots").iterdir())
            for old in snaps[:-self.MAX_SNAPSHOTS]:
                shutil.rmtree(old, ignore_errors=True)
        except Exception:
            pass

    def last_backup(self):
        try:
            return json.loads((self.ROOT / "data_quality" / "last_backup.json").read_text())
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
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "destination": str(dest), "off_machine": off, "destination_note": note,
            "last_backup_at": (last or {}).get("timestamp"),
            "hours_since_backup": age_h,
            "files_protected": (last or {}).get("files_backed_up", 0),
            "verified": (last or {}).get("verified_by_hash", 0),
            "unprotected_unrecoverable_paths": unprotected,
            "why_it_matters": ("options_reality and the PIT/earnings panels accrue FORWARD ONLY "
                               "— no API can rebuild them. Losing the disk restarts the options "
                               "edge experiment from zero."),
            "status": "DISASTER_RECOVERY_STATUS",
        }
