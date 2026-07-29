"""A backup killed mid-run leaves the marker stale and the error-path alert never fires — this guard
closes that silent hole by screaming on MARKER age, throttled so a persistent gap warns periodically."""

from datetime import datetime, timedelta

from app.services.disaster_recovery_engine import DisasterRecoveryEngine as D


class FakeNotifier:
    calls = []

    def record(self, **kw):
        FakeNotifier.calls.append(kw)


def _patch(monkeypatch, tmp_path, last_ts):
    FakeNotifier.calls = []
    monkeypatch.setattr(D, "STALE_MARKER", tmp_path / "stale.json")
    monkeypatch.setattr(D, "last_backup",
                        lambda self: ({"timestamp": last_ts} if last_ts else None))
    monkeypatch.setattr("app.services.operator_notification_engine.OperatorNotificationEngine",
                        lambda: FakeNotifier())


def test_fresh_backup_no_alert(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, datetime.utcnow().isoformat())
    assert D().alert_if_stale()["status"] == "BACKUP_FRESH"
    assert FakeNotifier.calls == []


def test_stale_backup_screams(monkeypatch, tmp_path):
    old = (datetime.utcnow() - timedelta(hours=30)).isoformat()
    _patch(monkeypatch, tmp_path, old)
    r = D().alert_if_stale()
    assert r["status"] == "BACKUP_STALE_ALERTED"
    assert len(FakeNotifier.calls) == 1
    assert FakeNotifier.calls[0]["severity"] == "CRITICAL"


def test_never_backed_up_screams(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, None)
    assert D().alert_if_stale()["status"] == "BACKUP_STALE_ALERTED"


def test_stale_alert_is_throttled(monkeypatch, tmp_path):
    old = (datetime.utcnow() - timedelta(hours=30)).isoformat()
    _patch(monkeypatch, tmp_path, old)
    assert D().alert_if_stale()["status"] == "BACKUP_STALE_ALERTED"
    # immediate re-check within the throttle window must NOT re-alert
    assert D().alert_if_stale()["status"] == "BACKUP_STALE_THROTTLED"
    assert len(FakeNotifier.calls) == 1
