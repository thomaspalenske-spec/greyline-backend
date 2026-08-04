"""Off-box deadman switch — the one alert that survives THIS Mac dying.

Every existing GreyLine alert (iMessage/webhook/macOS) is sent FROM this Mac, so it covers "service
broken + operator away" but NOT a fully-dead Mac (crash, power loss, network loss). Then nothing tells
the operator the system is down — positions are held only by the broker-side stops, silently.

This closes that gap WITHOUT a third-party signup (operator refused ntfy.sh): the service pushes a tiny
HEARTBEAT file to a dedicated branch on the existing GitHub remote every few minutes (a network git push
is proven to work from the LaunchAgent, unlike the TCC-blocked filesystem backups). A scheduled GitHub
ACTION — running on GitHub's infra, OFF this Mac — checks the heartbeat's age and FAILS the workflow when
it goes stale; GitHub then emails the repo owner on the failed run. A dead Mac cannot suppress that email.
See .github/workflows/deadman-heartbeat-check.yml for the off-box half.

Lightweight by design: one <1KB file, force-pushed to its own branch (history irrelevant), self-gated to
~INTERVAL_MIN so it never floods. Reuses the same origin credential the git backup already proved works.
"""

import json
import subprocess
from datetime import datetime
from os import getenv
from pathlib import Path


class DeadmanHeartbeatEngine:

    REPO = Path("app/data/.deadman_heartbeat")
    BRANCH = "deadman-heartbeat"
    HEARTBEAT_REL = "heartbeat.json"
    MARKER = Path("app/data/data_quality/deadman_heartbeat_last.json")
    INTERVAL_MIN_DEFAULT = 5.0

    def _interval_min(self):
        try:
            v = getenv("GREYLINE_DEADMAN_INTERVAL_MIN", "")
            return float(v) if str(v).strip() else self.INTERVAL_MIN_DEFAULT
        except (TypeError, ValueError):
            return self.INTERVAL_MIN_DEFAULT

    def _origin_url(self):
        try:
            return subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True,
                                  text=True, timeout=15).stdout.strip()
        except Exception:
            return ""

    def _git(self, *args, timeout=90):
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
            self._git("config", "user.email", "greyline-deadman@local")
            self._git("config", "user.name", "GreyLine Deadman Heartbeat")
        self._git("remote", "remove", "origin")
        self._git("remote", "add", "origin", url)
        return True, url

    def _context(self):
        """Cheap, non-blocking context stamped into the heartbeat — useful last-known-state if the Mac
        dies. NEVER makes a broker call (must not block or fail the heartbeat)."""
        ctx = {}
        try:
            from app.services.background_scheduler_service import BackgroundSchedulerService as B
            ctx["scheduler_cycles"] = getattr(B, "_cycle_count", None) or getattr(B, "cycle_count", None)
        except Exception:
            pass
        return ctx

    def _mark(self, at, pushed, detail=None):
        try:
            self.MARKER.parent.mkdir(parents=True, exist_ok=True)
            self.MARKER.write_text(json.dumps({"at": at, "pushed": bool(pushed), "detail": detail}))
        except Exception:
            pass

    def minutes_since(self):
        try:
            d = json.loads(self.MARKER.read_text())
            if not d.get("pushed"):
                return None
            return round((datetime.utcnow() - datetime.fromisoformat(str(d.get("at")))).total_seconds() / 60.0, 2)
        except Exception:
            return None

    def push(self):
        ok, info = self._ensure_repo()
        if not ok:
            self._mark(datetime.utcnow().isoformat(), False, info)
            return {"status": "DEADMAN_NO_REMOTE", "ok": False, "detail": info}
        now = datetime.utcnow()
        payload = {
            "at": now.isoformat(),
            "epoch": int(now.timestamp()),
            "host": "greyline-service",
            "note": "GreyLine is alive. If this file goes stale, the Mac/service is DOWN — the off-box "
                    "GitHub Action fails and emails the operator. Positions are then held by broker stops.",
            **self._context(),
        }
        (self.REPO / self.HEARTBEAT_REL).write_text(json.dumps(payload, indent=2))
        self._git("add", "-A")
        self._git("commit", "-q", "-m", f"heartbeat {payload['at']}")
        pr = self._git("push", "-q", "--force", "origin", f"HEAD:{self.BRANCH}", timeout=120)
        pushed = pr.returncode == 0
        self._mark(payload["at"], pushed, None if pushed else (pr.stderr or "")[:160])
        return {"status": "DEADMAN_HEARTBEAT_PUSHED" if pushed else "DEADMAN_PUSH_FAILED",
                "ok": pushed, "branch": self.BRANCH, "at": payload["at"],
                "detail": None if pushed else ("push failed: " + (pr.stderr or "")[:160])}

    def push_if_due(self):
        ms = self.minutes_since()
        if ms is not None and ms < self._interval_min():
            return {"status": "DEADMAN_NOT_DUE", "minutes_since": ms}
        return self.push()

    def status(self):
        ms = self.minutes_since()
        marker = {}
        try:
            marker = json.loads(self.MARKER.read_text())
        except Exception:
            pass
        return {
            "timestamp": datetime.utcnow().isoformat(), "status": "DEADMAN_HEARTBEAT_STATUS",
            "branch": self.BRANCH, "interval_min": self._interval_min(),
            "last_push": marker or None, "minutes_since_push": ms,
            "ever_pushed": bool(marker.get("pushed")) if marker else False,
            "note": ("Off-box deadman: pushes a heartbeat to GitHub every ~interval; a scheduled GitHub "
                     "Action fails + emails the operator if it goes stale (covers a fully-dead Mac)."),
        }
