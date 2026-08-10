"""Acknowledging an alert can SNOOZE its type so a still-true, already-seen condition doesn't re-nag.

Without this, a condition that re-asserts every cycle (a real over-deployment being resolved at the next
open) re-records a fresh unread CRITICAL ~every 30 min, so acknowledging it clears the banner for one
cycle then it's back. Snooze quiets ONLY that event_type for a window; a different type still records,
and the type re-surfaces when the snooze lapses (nothing is hidden — the live state stays on the dashboard).
"""

import json
from datetime import datetime, timedelta

from app.services.operator_notification_engine import OperatorNotificationEngine as N


def _engine(tmp_path):
    n = N()
    n.ledger_file = tmp_path / "notif.jsonl"
    n.snooze_file = tmp_path / "snooze.json"
    return n


def test_ack_all_snoozes_type_and_record_skips_it(tmp_path):
    n = _engine(tmp_path)
    n.record("BOOK_OVER_DEPLOYED", "Over-deployed", "m", severity="WARNING")
    res = n.acknowledge_all(snooze_hours=6)
    assert res["acknowledged_count"] == 1 and "BOOK_OVER_DEPLOYED" in res["snoozed_event_types"]
    # the same type is now snoozed -> a re-fire is skipped, not re-nagged
    r = n.record("BOOK_OVER_DEPLOYED", "Over-deployed again", "m", severity="WARNING")
    assert r["status"] == "OPERATOR_NOTIFICATION_SNOOZED" and r["notification_recorded"] is False
    assert n.unread()["unread_count"] == 0


def test_a_different_type_is_not_snoozed(tmp_path):
    n = _engine(tmp_path)
    n.record("BOOK_OVER_DEPLOYED", "Over", "m", severity="WARNING")
    n.acknowledge_all(snooze_hours=6)
    r = n.record("SOMETHING_NEW", "A new problem", "m", severity="WARNING")
    assert r["notification_recorded"] is True                 # unrelated alert still gets through
    assert n.unread()["unread_count"] == 1


def test_snooze_lapses_then_alerts_again(tmp_path):
    n = _engine(tmp_path)
    n.record("FP", "x", "m", severity="WARNING")
    n.acknowledge_all(snooze_hours=6)
    assert n.record("FP", "x2", "m", severity="WARNING")["status"] == "OPERATOR_NOTIFICATION_SNOOZED"
    d = json.loads(n.snooze_file.read_text())
    d["FP"] = (datetime.utcnow() - timedelta(hours=1)).isoformat()   # expire it
    n.snooze_file.write_text(json.dumps(d))
    assert n.record("FP", "x3", "m", severity="WARNING")["notification_recorded"] is True


def test_ack_all_without_snooze_does_not_snooze(tmp_path):
    n = _engine(tmp_path)
    n.record("FP", "x", "m", severity="WARNING")
    res = n.acknowledge_all()                                 # no snooze_hours
    assert res["snoozed_event_types"] == []
    assert n.record("FP", "x2", "m", severity="WARNING")["notification_recorded"] is True
