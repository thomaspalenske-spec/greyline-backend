"""Get a CRITICAL event OFF this machine — the third redundancy gap.

Every notification GreyLine raises lands in one place: a JSONL ledger the dashboard reads. That
is fine for things the operator will see when they next look. It is useless for the failure that
matters most — the one that happens while nobody is looking. The proof case already happened: a
backfill failed for hours AND reported "complete." No human saw it because nothing left the box.

An alert that never leaves the machine is not an alert; it is a log line. So this engine fans a
critical event out to whatever EXTERNAL channel the operator has configured, and — this is the
part that keeps the redundancy honest — it reports plainly when NO external channel exists, so
"we have alerting" can never quietly become the next silent lie.

CHANNELS (all opt-in via env; none is configured by default):
  * GREYLINE_ALERT_IMESSAGE_TO   a phone number or Apple ID. Sends via the Messages app already
                                 signed in on this Mac — no third-party account, no subscription.
                                 Reaches the operator's phone through Apple. Counts as external
                                 (it reaches the operator remotely) with ONE honest caveat: the
                                 send is issued from THIS Mac, so it covers the "GreyLine running,
                                 hit a CRITICAL, operator away" case — the actual proof case — but
                                 NOT the Mac being fully dead. Nothing without an off-box deadman
                                 covers that; positions in that case are held by the broker stops.
  * GREYLINE_ALERT_WEBHOOK_URL   a Slack/Discord/generic incoming webhook. JSON POST.
  * GREYLINE_ALERT_NTFY_TOPIC    an ntfy.sh topic (no account needed): POSTs to https://ntfy.sh/<topic>.
                                 Set GREYLINE_ALERT_NTFY_SERVER to self-host.
  * macOS local notification     an on-machine fallback (osascript). Better than nothing when the
                                 operator is AT the machine, but NOT redundancy — it dies with the
                                 box. Reported as on-machine, never counted as an external channel.

DESIGN CHOICES:
  * Best-effort and non-blocking-by-intent: a failing alert channel must never take down the
    thing it is trying to warn about. Every send is wrapped; failures are recorded, not raised.
  * Deduplicated: the same critical condition every scheduler cycle would become a pager storm.
    A fingerprint + cooldown means one page per condition per window, not one per cycle.
  * Honest status: status() says exactly which channels are live and whether ANY is off-machine.
"""

import json
import urllib.request
from datetime import datetime, timedelta
from os import getenv
from pathlib import Path


class ExternalAlertEngine:

    STATE = Path("app/data/notifications/external_alert_state.json")
    COOLDOWN_MIN = 30          # min spacing between the (few) pages of one condition
    # HARD CAP: text the SAME alert at most this many times per episode, then go SILENT until it resolves.
    # Without it a condition that re-asserts every cycle (e.g. "Mission book OVER-deployed") pages the
    # operator indefinitely — 6 identical texts is noise, not signal. An episode ends when the condition
    # stops firing (no dispatch attempts) for EPISODE_RESET_MIN, so a genuine recurrence still alerts.
    MAX_SENDS_PER_FP = 2
    EPISODE_RESET_MIN = 240    # 4h of quiet (no attempts) starts a fresh episode -> the cap resets
    TIMEOUT_S = 6

    @classmethod
    def _max_sends(cls):
        from os import getenv
        try:
            v = getenv("GREYLINE_MAX_ALERT_SENDS", "")
            return max(1, int(v)) if str(v).strip() else cls.MAX_SENDS_PER_FP
        except (TypeError, ValueError):
            return cls.MAX_SENDS_PER_FP

    # --------------------------------------------------------------- config

    @staticmethod
    def _webhook_url():
        return (getenv("GREYLINE_ALERT_WEBHOOK_URL", "") or "").strip()

    @staticmethod
    def _ntfy_topic():
        return (getenv("GREYLINE_ALERT_NTFY_TOPIC", "") or "").strip()

    @staticmethod
    def _ntfy_server():
        return (getenv("GREYLINE_ALERT_NTFY_SERVER", "https://ntfy.sh") or "https://ntfy.sh").strip().rstrip("/")

    @staticmethod
    def _imessage_to():
        return (getenv("GREYLINE_ALERT_IMESSAGE_TO", "") or "").strip()

    @staticmethod
    def _macos_enabled():
        return (getenv("GREYLINE_ALERT_MACOS_LOCAL", "true") or "true").strip().lower() == "true"

    def external_channels(self):
        """Channels that reach the operator OFF this machine (see the iMessage caveat in the
        module docstring — it reaches the phone but is still sent from this Mac)."""
        ch = []
        if self._imessage_to():
            ch.append("imessage")
        if self._webhook_url():
            ch.append("webhook")
        if self._ntfy_topic():
            ch.append("ntfy")
        return ch

    def has_external_channel(self):
        return bool(self.external_channels())

    # ---------------------------------------------------------------- state

    def _load_state(self):
        try:
            return json.loads(self.STATE.read_text())
        except Exception:
            return {"last_sent": {}}

    def _save_state(self, st):
        try:
            self.STATE.parent.mkdir(parents=True, exist_ok=True)
            self.STATE.write_text(json.dumps(st, indent=2))
        except Exception:
            pass

    def _cooling_down(self, fingerprint, st, now):
        ts = (st.get("last_sent") or {}).get(fingerprint)
        if not ts:
            return False
        try:
            return (now - datetime.fromisoformat(ts)) < timedelta(minutes=self.COOLDOWN_MIN)
        except Exception:
            return False

    # ------------------------------------------------------------- channels

    def _post_json(self, url, payload, headers=None):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req, timeout=self.TIMEOUT_S) as r:
            return 200 <= r.status < 300

    def _post_text(self, url, text, headers=None):
        req = urllib.request.Request(url, data=text.encode(), method="POST", headers=headers or {})
        with urllib.request.urlopen(req, timeout=self.TIMEOUT_S) as r:
            return 200 <= r.status < 300

    def _send_webhook(self, title, message, severity):
        url = self._webhook_url()
        if not url:
            return None
        # Slack and Discord both accept a bare {"text"/"content": ...}; send both keys.
        line = f"[{severity}] GreyLine — {title}\n{message}"
        try:
            ok = self._post_json(url, {"text": line, "content": line})
            return {"channel": "webhook", "ok": bool(ok)}
        except Exception as e:
            return {"channel": "webhook", "ok": False, "error": str(e)[:100]}

    def _send_ntfy(self, title, message, severity):
        topic = self._ntfy_topic()
        if not topic:
            return None
        url = f"{self._ntfy_server()}/{topic}"
        prio = "urgent" if severity == "CRITICAL" else "high"
        try:
            ok = self._post_text(url, message, headers={
                "Title": f"GreyLine {severity}: {title}"[:250],
                "Priority": prio,
                "Tags": "rotating_light" if severity == "CRITICAL" else "warning",
            })
            return {"channel": "ntfy", "ok": bool(ok)}
        except Exception as e:
            return {"channel": "ntfy", "ok": False, "error": str(e)[:100]}

    def _send_imessage(self, title, message, severity):
        to = self._imessage_to()
        if not to:
            return None
        body = f"GreyLine {severity}: {title}\n{message}"[:1000]
        # AppleScript is quote-delimited; strip the two chars that would break the string or the
        # shell-free osascript -e argument. Newlines are fine inside an AppleScript string.
        safe_to = to.replace('"', "").replace("\\", "")
        safe_body = body.replace('"', "'").replace("\\", "")
        script = (
            'tell application "Messages"\n'
            '  set svc to 1st service whose service type = iMessage\n'
            f'  set toBuddy to participant "{safe_to}" of svc\n'
            f'  send "{safe_body}" to toBuddy\n'
            'end tell')
        try:
            import subprocess
            r = subprocess.run(["osascript", "-e", script], timeout=self.TIMEOUT_S,
                               capture_output=True, text=True)
            if r.returncode == 0:
                return {"channel": "imessage", "ok": True}
            return {"channel": "imessage", "ok": False,
                    "error": (r.stderr or "osascript failed").strip()[:120]}
        except Exception as e:
            return {"channel": "imessage", "ok": False, "error": str(e)[:120]}

    def _send_macos(self, title, message, severity):
        if not self._macos_enabled():
            return None
        try:
            import subprocess
            safe_t = str(title).replace('"', "'")[:120]
            safe_m = str(message).replace('"', "'")[:220]
            script = (f'display notification "{safe_m}" with title '
                      f'"GreyLine {severity}" subtitle "{safe_t}"')
            subprocess.run(["osascript", "-e", script], timeout=self.TIMEOUT_S,
                           capture_output=True)
            return {"channel": "macos_local", "ok": True, "off_machine": False}
        except Exception as e:
            return {"channel": "macos_local", "ok": False, "error": str(e)[:100]}

    # ------------------------------------------------------------- dispatch

    def dispatch(self, title, message, severity="CRITICAL", fingerprint=None, force=False,
                 dry_run=False):
        """Fan a single event out to every configured channel, deduplicated by fingerprint.

        Returns an honest report: which channels fired, whether ANY was off-machine, and — when
        nothing external is configured — that the alert stayed on the box.
        """
        now = datetime.utcnow()
        fp = fingerprint or f"{severity}:{title}"
        st = self._load_state()

        # EPISODE tracking for the hard send cap. `sends[fp] = {count, last_attempt, last_sent}`.
        sends = st.setdefault("sends", {})
        rec = dict(sends.get(fp) or {"count": 0, "last_attempt": None, "last_sent": None})
        # A quiet gap (no dispatch ATTEMPTS for EPISODE_RESET_MIN) means the previous burst is over —
        # reset the counter so a genuine recurrence of the SAME condition can page again.
        if rec.get("last_attempt"):
            try:
                if (now - datetime.fromisoformat(rec["last_attempt"])) > timedelta(minutes=self.EPISODE_RESET_MIN):
                    rec = {"count": 0, "last_attempt": None, "last_sent": None}
            except Exception:
                pass
        rec["last_attempt"] = now.isoformat()

        def _persist(result):
            sends[fp] = rec
            self._save_state(st)
            return result

        # HARD CAP first: once the SAME alert has paged MAX_SENDS times this episode, stay silent (even on
        # force — force bypasses the spacing cooldown, NOT the absolute cap). Prevents endless identical texts.
        if rec.get("count", 0) >= self._max_sends():
            return _persist({"status": "SUPPRESSED_MAX_SENDS", "fingerprint": fp,
                             "detail": (f"already paged {rec['count']}x this episode (max {self._max_sends()}) — "
                                        "silent until it resolves")})

        if not force and self._cooling_down(fp, st, now):
            return _persist({"status": "SUPPRESSED_COOLDOWN", "fingerprint": fp,
                             "detail": f"identical alert sent within {self.COOLDOWN_MIN}m"})

        if dry_run:
            return {"status": "DRY_RUN",
                    "would_use_external": self.external_channels(),
                    "would_use_macos": self._macos_enabled(),
                    "has_external_channel": self.has_external_channel()}

        results = [r for r in (self._send_imessage(title, message, severity),
                               self._send_webhook(title, message, severity),
                               self._send_ntfy(title, message, severity),
                               self._send_macos(title, message, severity)) if r is not None]

        external_ok = any(r.get("ok") and r["channel"] in ("imessage", "webhook", "ntfy")
                          for r in results)
        if external_ok:
            st.setdefault("last_sent", {})[fp] = now.isoformat()   # cooldown spacing state
            rec["count"] = rec.get("count", 0) + 1                  # count toward the per-episode cap
            rec["last_sent"] = now.isoformat()
        sends[fp] = rec
        self._save_state(st)

        return {
            "timestamp": now.isoformat(),
            "title": title, "severity": severity, "fingerprint": fp,
            "episode_send_count": rec.get("count", 0),
            "channels": results,
            "reached_off_machine": external_ok,
            "has_external_channel": self.has_external_channel(),
            "status": ("ALERT_DELIVERED_OFF_MACHINE" if external_ok
                       else "ALERT_STAYED_ON_MACHINE"),
            "warning": (None if external_ok else
                        "NO external alert channel is configured — this critical event did NOT "
                        "leave the machine. Set GREYLINE_ALERT_WEBHOOK_URL or "
                        "GREYLINE_ALERT_NTFY_TOPIC so failures can reach you when you are away."),
        }

    def status(self):
        ext = self.external_channels()
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "external_channels": ext,
            "has_external_channel": bool(ext),
            "macos_local_fallback": self._macos_enabled(),
            "cooldown_minutes": self.COOLDOWN_MIN,
            "note": ("external channels survive this machine dying; macOS local does NOT and is a "
                     "convenience only. With no external channel, a failure that happens while "
                     "the operator is away is invisible — the exact backfill-silent-failure case."),
            "status": "EXTERNAL_ALERT_STATUS",
        }
