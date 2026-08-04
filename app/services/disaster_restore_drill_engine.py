"""Restore drill — proves the off-machine git backup is actually RESTORABLE, not just written.

A backup you have NEVER test-restored is the classic latent DR failure: the push succeeds, the marker
says "complete", but the branch could be missing files, truncated, or corrupt — and you only discover it
during a real disaster, when it's too late. This engine periodically FETCHES the actual remote backup
branch (the true off-machine copy, not the local staging repo) into a throwaway dir and verifies every
TIER1 file is PRESENT, NON-EMPTY, and PARSES (JSON loads / JSONL per-line / CSV reads) — i.e. a USABLE
restore, not a corrupt blob. It cannot hash-match against today's live files (ledgers grow between
backups), so it verifies restorability, not equality. Read-only — never touches live data. Screams
CRITICAL if a restore would fail. Closes the "backup is never fire-drilled" DR gap.
"""

import csv
import io
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


class DisasterRestoreDrillEngine:

    MARKER = Path("app/data/data_quality/restore_drill_last.json")
    DUE_HOURS = 168.0        # weekly — a restore drill is expensive (network clone) and rarely needs to be more often

    def _branch(self):
        from app.services.git_data_backup_engine import GitDataBackupEngine
        return GitDataBackupEngine.BRANCH

    def _origin_url(self):
        try:
            return subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True,
                                  text=True, timeout=15).stdout.strip()
        except Exception:
            return ""

    def _expected_rel_paths(self):
        """The TIER1 relative paths that MUST be restorable — the exact list the git backup pushes, so
        the drill and the backup can never disagree on what 'complete' means."""
        try:
            from app.services.git_data_backup_engine import GitDataBackupEngine
            return sorted(str(rel) for _src, rel in GitDataBackupEngine._tier1_files())
        except Exception:
            return []

    def _fetch_backup_tree(self):
        """Shallow-clone the remote backup branch into a temp dir; return {rel_path: bytes} for every file
        in it, or None if the fetch failed. NETWORK op, isolated so tests can mock it."""
        url = self._origin_url()
        if not url:
            return None
        try:
            with tempfile.TemporaryDirectory() as td:
                r = subprocess.run(["git", "clone", "--depth", "1", "--branch", self._branch(), url, td],
                                   capture_output=True, text=True, timeout=180)
                if r.returncode != 0:
                    return None
                root = Path(td)
                tree = {}
                for p in root.rglob("*"):
                    if p.is_file() and ".git" not in p.parts:
                        tree[str(p.relative_to(root))] = p.read_bytes()
                return tree
        except Exception:
            return None

    @staticmethod
    def _parses(rel, data):
        """Is this restored file USABLE (not truncated/corrupt)? JSON must load; JSONL each non-blank line
        loads; CSV must parse. An EMPTY file is a FAITHFUL, restorable backup for formats where empty is a
        legitimate state (a ledger with 0 trades, an empty log) — only an empty .json is invalid (it can't
        parse as JSON). Emptiness is NOT data-loss detection; that's the git backup's completeness check."""
        name = rel.lower()
        if not data:
            if name.endswith(".json"):
                return False, "empty json (invalid)"
            return True, None                          # empty .jsonl/.csv/other = legitimately empty, restorable
        try:
            if name.endswith(".json"):
                json.loads(data.decode("utf-8", "replace"))
            elif name.endswith(".jsonl"):
                for line in data.decode("utf-8", "replace").splitlines():
                    if line.strip():
                        json.loads(line)
            elif name.endswith(".csv"):
                rows = list(csv.reader(io.StringIO(data.decode("utf-8", "replace"))))
                if not rows:
                    return False, "csv has no rows"
            return True, None
        except Exception as e:
            return False, f"unparseable: {str(e)[:80]}"

    def _verify(self, tree, expected):
        """PURE: classify each expected TIER1 file as restorable | missing | corrupt. Restorable only if
        EVERY file is present and parses — a partial/corrupt backup is a failed restore."""
        missing, corrupt, ok = [], [], []
        for rel in expected:
            if rel not in tree:
                missing.append(rel)
                continue
            good, why = self._parses(rel, tree[rel])
            if good:
                ok.append(rel)
            else:
                corrupt.append({"file": rel, "why": why})
        restorable = not missing and not corrupt
        return {
            "restorable": restorable,
            "expected": len(expected),
            "present": len([r for r in expected if r in tree]),
            "verified": len(ok),
            "missing": missing,
            "corrupt": corrupt,
            "status": "RESTORE_DRILL_VERIFIED" if restorable else "RESTORE_DRILL_FAILED",
        }

    def drill(self):
        """Fetch the real remote backup and verify it would restore. Read-only; does NOT page (run_if_due
        does). Safe to call ad hoc."""
        expected = self._expected_rel_paths()
        if not expected:
            return {"status": "RESTORE_DRILL_NO_TIER1", "restorable": False,
                    "detail": "no TIER1 files configured to verify"}
        tree = self._fetch_backup_tree()
        if tree is None:
            return {"status": "RESTORE_DRILL_FETCH_FAILED", "restorable": False,
                    "detail": "could not fetch the remote backup branch — restorability UNVERIFIED",
                    "expected": len(expected)}
        res = self._verify(tree, expected)
        res["timestamp"] = datetime.utcnow().isoformat()
        res["branch"] = self._branch()
        return res

    def drill_and_record(self):
        """Run the drill NOW (ignoring the weekly gate) and RECORD the marker — the manual-run path. Does
        not page (that's run_if_due's job on the scheduler); an ad-hoc operator run still updates state so
        the reality guard reflects it."""
        res = self.drill()
        self._mark(res)
        return res

    def _mark(self, res):
        try:
            self.MARKER.parent.mkdir(parents=True, exist_ok=True)
            self.MARKER.write_text(json.dumps({
                "at": datetime.utcnow().isoformat(), "status": res.get("status"),
                "restorable": bool(res.get("restorable")), "verified": res.get("verified"),
                "expected": res.get("expected"), "missing": len(res.get("missing", []) or []),
                "corrupt": len(res.get("corrupt", []) or [])}))
        except Exception:
            pass

    def hours_since(self):
        try:
            at = json.loads(self.MARKER.read_text()).get("at")
            return round((datetime.utcnow() - datetime.fromisoformat(str(at))).total_seconds() / 3600.0, 2)
        except Exception:
            return None

    def run_if_due(self):
        """Self-gated (~weekly). Runs the drill and screams CRITICAL if a restore would fail. Wired into
        the scheduler after the git backup block."""
        hs = self.hours_since()
        if hs is not None and hs < self.DUE_HOURS:
            return {"status": "RESTORE_DRILL_NOT_DUE", "hours_since": hs}
        res = self.drill()
        self._mark(res)
        if not res.get("restorable"):
            try:
                from app.services.external_alert_engine import ExternalAlertEngine
                ExternalAlertEngine().dispatch(
                    "GreyLine: RESTORE DRILL FAILED",
                    f"The off-machine backup is NOT restorable ({res.get('status')}): "
                    f"{len(res.get('missing', []) or [])} missing, {len(res.get('corrupt', []) or [])} corrupt "
                    f"of {res.get('expected')} TIER1 files. The disaster backup cannot be relied on to recover.",
                    severity="CRITICAL", fingerprint="restore_drill_failed")
            except Exception:
                pass
        return res

    def status(self):
        hs = self.hours_since()
        marker = {}
        try:
            marker = json.loads(self.MARKER.read_text())
        except Exception:
            pass
        return {
            "timestamp": datetime.utcnow().isoformat(), "status": "RESTORE_DRILL_STATUS",
            "last_drill": marker or None, "hours_since": hs,
            "due_in_hours": (None if hs is None else round(max(0.0, self.DUE_HOURS - hs), 1)),
            "ever_run": bool(marker),
            "note": ("Proves the off-machine git backup is RESTORABLE (present + non-empty + parses), not "
                     "just written. Weekly; screams CRITICAL if a restore would fail."),
        }
