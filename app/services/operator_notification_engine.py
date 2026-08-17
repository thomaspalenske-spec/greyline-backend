import json
from app.services.time_utils import parse_utc
from datetime import datetime, timedelta
from pathlib import Path
from app.services.ttl_cache import ttl_cached


class OperatorNotificationEngine:
    """
    Persistent operator notification ledger.
    Records events GreyLine should not let disappear silently.
    """

    def __init__(self):
        self.ledger_file = Path("app/data/operator_notifications/operator_notifications.jsonl")
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        self.snooze_file = self.ledger_file.parent / "snoozed_event_types.json"

    # ---- snooze: an acknowledged, still-true condition should not immediately re-nag ---------------
    def _snoozes(self):
        try:
            return json.loads(self.snooze_file.read_text())
        except Exception:
            return {}

    def _save_snoozes(self, d):
        try:
            self.snooze_file.write_text(json.dumps(d, indent=2))
        except Exception:
            pass

    def _is_snoozed(self, event_type):
        until = self._snoozes().get(str(event_type))
        if not until:
            return False
        try:
            return datetime.utcnow() < parse_utc(until)
        except Exception:
            return False

    def snooze(self, event_type, hours):
        """Quiet one event_type for `hours` — the operator acknowledged it and doesn't want it re-nagging
        while it's still true. Only THIS type is affected; it re-surfaces when the snooze lapses."""
        d = self._snoozes()
        d[str(event_type)] = (datetime.utcnow() + timedelta(hours=float(hours))).isoformat()
        self._save_snoozes(d)
        return {"event_type": event_type, "snoozed_until": d[str(event_type)]}

    def _read(self):
        if not self.ledger_file.exists():
            return []
        rows = []
        for line in self.ledger_file.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        return rows

    def _write(self, rows):
        self.ledger_file.write_text(
            "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else "")
        )

    def record(self, event_type, title, message, severity="INFO", source="GREYLINE", payload=None):
        # SNOOZED: the operator already acknowledged this alert type and asked for quiet. Skip re-recording
        # (and re-paging) an already-known, still-true condition until the snooze lapses — the live state is
        # still visible on the dashboard (exposure gate / reality guard), so nothing is hidden.
        if self._is_snoozed(event_type):
            return {"notification_recorded": False, "event_type": event_type,
                    "status": "OPERATOR_NOTIFICATION_SNOOZED"}
        payload = payload or {}
        notification_id = f"{event_type}-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"

        row = {
            "notification_id": notification_id,
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "title": title,
            "message": message,
            "severity": severity,
            "source": source,
            "payload": payload,
            "acknowledged": False,
            "acknowledged_at": None,
        }

        with self.ledger_file.open("a") as f:
            f.write(json.dumps(row) + "\n")

        # A CRITICAL event that only lands in this ledger is invisible the moment the operator
        # is not looking at the dashboard — which is precisely when it matters most. Escalate it
        # off the machine (best-effort; a failing alert channel must never break the recording).
        external = None
        if str(severity).upper() == "CRITICAL":
            try:
                from app.services.external_alert_engine import ExternalAlertEngine
                external = ExternalAlertEngine().dispatch(
                    title=title, message=message, severity="CRITICAL",
                    fingerprint=f"{event_type}:{title}")
            except Exception as exc:
                external = {"status": "EXTERNAL_ALERT_FAILED", "error": repr(exc)[:120]}

        return {
            "notification_recorded": True,
            "notification": row,
            "external_alert": external,
            "status": "OPERATOR_NOTIFICATION_RECORDED",
        }

    @ttl_cached(30, env_key="GREYLINE_SHADOW_CACHE_TTL")
    def unread(self, limit=25):
        cutoff = datetime.utcnow() - timedelta(hours=24)
        rows = []
        historical_unread_count = 0

        for r in self._read():
            if r.get("acknowledged") is True:
                continue

            historical_unread_count += 1

            ts_raw = str(r.get("timestamp") or "")
            try:
                ts = parse_utc(ts_raw)
            except Exception:
                ts = datetime.min

            if ts < cutoff:
                continue

            if (
                r.get("event_type") == "EXECUTION_BLOCKED"
                and "EXECUTE_SIGNAL_BLOCKED_READ_ONLY" in str(r.get("title") or "")
            ):
                continue

            rows.append(r)

        rows = sorted(rows, key=lambda r: r.get("timestamp", ""), reverse=True)[:limit]
        unread_critical_count = sum(1 for r in rows if str(r.get("severity")).upper() == "CRITICAL")
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "OperatorNotificationEngine",
            "unread_count": len(rows),
            "unread_critical_count": unread_critical_count,   # genuine attention items vs routine backlog
            "historical_unread_count": historical_unread_count,
            "active_alert_window_hours": 24,
            "read_only_execution_blocks_suppressed": True,
            "notifications": rows,
            "status": "OPERATOR_NOTIFICATIONS_READY",
        }

    def acknowledge(self, notification_id):
        rows = self._read()
        matched = False

        for r in rows:
            if r.get("notification_id") == notification_id:
                r["acknowledged"] = True
                r["acknowledged_at"] = datetime.utcnow().isoformat()
                matched = True

        if matched:
            self._write(rows)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "notification_id": notification_id,
            "acknowledged": matched,
            "status": "OPERATOR_NOTIFICATION_ACKNOWLEDGED" if matched else "OPERATOR_NOTIFICATION_NOT_FOUND",
        }

    def acknowledge_all(self, snooze_hours=None):
        rows = self._read()
        now = datetime.utcnow().isoformat()
        previous_unread_count = 0
        acknowledged_count = 0
        acked_types = set()

        for r in rows:
            if r.get("acknowledged") is not True:
                previous_unread_count += 1
                r["acknowledged"] = True
                r["acknowledged_at"] = now
                acknowledged_count += 1
                if r.get("event_type"):
                    acked_types.add(str(r.get("event_type")))

        if acknowledged_count:
            self._write(rows)

        # Optionally SNOOZE every acknowledged type so a still-true, already-seen condition (e.g. a real
        # over-deployment being resolved at the next open) doesn't immediately re-nag. Each re-surfaces
        # when the snooze lapses; a NEW/different alert type is never snoozed.
        snoozed = []
        if snooze_hours and acked_types:
            d = self._snoozes()
            until = (datetime.utcnow() + timedelta(hours=float(snooze_hours))).isoformat()
            for et in acked_types:
                d[et] = until
                snoozed.append(et)
            self._save_snoozes(d)

        remaining_unread_count = len([r for r in rows if r.get("acknowledged") is not True])

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "OperatorNotificationEngine",
            "previous_unread_count": previous_unread_count,
            "acknowledged_count": acknowledged_count,
            "remaining_unread_count": remaining_unread_count,
            "snoozed_event_types": sorted(snoozed),
            "snooze_hours": snooze_hours,
            "status": "OPERATOR_NOTIFICATIONS_ACKNOWLEDGED_ALL",
        }

