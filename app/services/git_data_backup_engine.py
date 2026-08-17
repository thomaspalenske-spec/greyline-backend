"""Off-machine backup of the UNRECOVERABLE data via git push — the only channel the always-on
service can actually use.

The service is a macOS LaunchAgent that TCC sandboxes from every off-machine FILESYSTEM location
(iCloud Drive AND external/removable volumes) — it silently sees an empty directory, so the
DisasterRecoveryEngine (iCloud/external) backup can't run from the service. A NETWORK git push is
not a TCC-protected filesystem op, so it works regardless.

This keeps a self-contained git repo (app/data/.data_backup, gitignored by the main repo) holding
copies of the TIER1 unrecoverable files, and pushes it to a DEDICATED branch on the existing GitHub
remote — reusing the already-authenticated credential, no new repo, and never touching the code
branch. Same TIER1 source list as DisasterRecoveryEngine, so the two agree on what's unrecoverable.
"""

import shutil
import subprocess
from datetime import datetime
from pathlib import Path


class GitDataBackupEngine:

    REPO = Path("app/data/.data_backup")
    BRANCH = "unrecoverable-data-backup"
    MARKER = Path("app/data/data_quality/git_data_backup_last.json")
    DUE_HOURS = 12.0

    def hours_since(self):
        try:
            import json
            rec = json.loads(self.MARKER.read_text())
            return round((datetime.utcnow() - datetime.fromisoformat(rec["at"])).total_seconds() / 3600, 2)
        except Exception:
            return None

    def _mark(self):
        try:
            import json
            self.MARKER.parent.mkdir(parents=True, exist_ok=True)
            self.MARKER.write_text(json.dumps({"at": datetime.utcnow().isoformat()}))
        except Exception:
            pass

    def run_if_due(self):
        """Best-effort, self-gated: push only when the last successful push is older than DUE_HOURS.
        Safe to call every scheduler cycle."""
        h = self.hours_since()
        if h is not None and h < self.DUE_HOURS:
            return {"status": "GIT_BACKUP_NOT_DUE", "hours_since": h}
        r = self.backup()
        if r.get("ok"):   # ok now means pushed AND complete (all TIER1 files present)
            self._mark()
        return r

    def _origin_url(self):
        try:
            return subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True,
                                  text=True, timeout=15).stdout.strip()
        except Exception:
            return ""

    @staticmethod
    def _tier1_files():
        """(abs source, relative path) for every unrecoverable file — reuse the single TIER1 list."""
        try:
            from app.services.disaster_recovery_engine import DisasterRecoveryEngine
            eng = DisasterRecoveryEngine()
            return eng._collect(list(eng.TIER1))
        except Exception:
            return []

    def _git(self, *args, timeout=120):
        """Run git in the backup repo. Non-interactive (no credential prompt can hang the service)."""
        import os
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        return subprocess.run(["git", "-C", str(self.REPO), *args], capture_output=True,
                              text=True, timeout=timeout, env=env)

    def _ensure_repo(self):
        url = self._origin_url()
        if not url:
            return False, "no origin remote to push to"
        if not (self.REPO / ".git").exists():
            self.REPO.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q", str(self.REPO)], timeout=30)
            self._git("checkout", "-q", "-b", self.BRANCH)
            self._git("config", "user.email", "greyline-backup@local")
            self._git("config", "user.name", "GreyLine Data Backup")
        # (re)point the remote at the current origin URL
        self._git("remote", "remove", "origin")
        self._git("remote", "add", "origin", url)
        return True, url

    def backup(self, push=True):
        ok, info = self._ensure_repo()
        if not ok:
            return {"status": "GIT_BACKUP_NO_REMOTE", "detail": info, "ok": False}

        files = self._tier1_files()
        expected = len(files)
        if not files:
            return {"status": "GIT_BACKUP_NOTHING", "ok": False, "files": 0}

        # mirror the TIER1 tree into the repo (clear + recopy so deletions propagate)
        for child in self.REPO.iterdir():
            if child.name == ".git":
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        copied = 0
        for src, rel in files:
            try:
                target = self.REPO / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                copied += 1
            except Exception:
                pass

        self._git("add", "-A")
        changed = bool(self._git("status", "--porcelain").stdout.strip())
        if changed:
            stamp = datetime.utcnow().isoformat()
            self._git("commit", "-q", "-m", f"unrecoverable-data backup {stamp} ({copied} files)")
        # COMPLETENESS: don't report success on a partial mirror. If fewer files copied than the TIER1
        # set expects (a swallowed copy failure), the backup is INCOMPLETE even if the push succeeds —
        # the same "trust the marker's count" fantasy the iCloud path was hardened against.
        complete = (copied == expected)
        if not push:
            return {"status": "GIT_BACKUP_INCOMPLETE" if not complete else
                    ("GIT_BACKUP_COMMITTED_LOCAL" if changed else "GIT_BACKUP_NO_CHANGE"),
                    "ok": complete, "files": copied, "expected": expected, "complete": complete,
                    "branch": self.BRANCH, "pushed": False}
        # ALWAYS sync the remote to local (force — single-writer snapshot branch, history irrelevant).
        # Idempotent when already in sync; also flushes any commit an earlier failed push left behind.
        pr = self._git("push", "-q", "--force", "origin", f"HEAD:{self.BRANCH}", timeout=180)
        pushed = pr.returncode == 0
        ok = pushed and complete
        return {"status": ("GIT_BACKUP_INCOMPLETE" if not complete else
                           ("GIT_BACKUP_PUSHED" if changed else "GIT_BACKUP_IN_SYNC")) if pushed
                          else "GIT_BACKUP_PUSH_FAILED",
                "ok": ok, "files": copied, "expected": expected, "complete": complete,
                "branch": self.BRANCH, "pushed": pushed, "changed": changed,
                "detail": ((f"remote '{self.BRANCH}' has {copied}/{expected} files"
                            + ("" if complete else " — INCOMPLETE, some TIER1 files failed to copy")))
                          if pushed else ("push failed: " + (pr.stderr or "")[:160])}

    def status(self):
        exists = (self.REPO / ".git").exists()
        last = None
        if exists:
            r = self._git("log", "-1", "--format=%cI %s")
            last = r.stdout.strip() or None
        return {"timestamp": datetime.utcnow().isoformat(), "repo": str(self.REPO),
                "branch": self.BRANCH, "initialized": exists, "last_commit": last,
                "status": "GIT_DATA_BACKUP_STATUS"}
