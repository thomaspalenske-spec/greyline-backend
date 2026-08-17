"""A backup killed mid-run leaves the marker stale and the error-path alert never fires — this guard
closes that silent hole by screaming on MARKER age, throttled so a persistent gap warns periodically."""

from datetime import datetime, timedelta

from app.services.disaster_recovery_engine import DisasterRecoveryEngine as D


class FakeNotifier:
    calls = []

    def record(self, **kw):
        FakeNotifier.calls.append(kw)


def _patch(monkeypatch, tmp_path, last_ts, git_h=999.0):
    # git_h = the age of the git off-machine channel the alert is now aware of. Default 999h (stale) so the
    # legacy "filesystem stale => CRITICAL" tests keep exercising the genuine double-gap path deterministically.
    FakeNotifier.calls = []
    monkeypatch.setattr(D, "STALE_MARKER", tmp_path / "stale.json")
    monkeypatch.setattr(D, "last_backup",
                        lambda self: ({"timestamp": last_ts} if last_ts else None))
    monkeypatch.setattr("app.services.operator_notification_engine.OperatorNotificationEngine",
                        lambda: FakeNotifier())
    import app.services.git_data_backup_engine as g
    monkeypatch.setattr(g.GitDataBackupEngine, "hours_since", lambda self: git_h)


def test_fresh_backup_no_alert(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, datetime.utcnow().isoformat())
    assert D().alert_if_stale()["status"] == "BACKUP_FRESH"
    assert FakeNotifier.calls == []


def test_both_channels_stale_is_critical(monkeypatch, tmp_path):
    old = (datetime.utcnow() - timedelta(hours=30)).isoformat()
    _patch(monkeypatch, tmp_path, old, git_h=40.0)          # git ALSO stale → genuine data-at-risk
    r = D().alert_if_stale()
    assert r["status"] == "BACKUP_STALE_ALERTED"
    assert len(FakeNotifier.calls) == 1
    assert FakeNotifier.calls[0]["severity"] == "CRITICAL"
    assert FakeNotifier.calls[0]["event_type"] == "BACKUP_STALE"


def test_fs_stale_but_git_fresh_is_warning_not_critical(monkeypatch, tmp_path):
    # The exact false-alarm the operator hit: filesystem snapshot stale (interrupted by restarts) but the
    # PRIMARY off-machine git backup is current → data IS protected → WARNING, never the CRITICAL alarm.
    old = (datetime.utcnow() - timedelta(hours=106)).isoformat()
    _patch(monkeypatch, tmp_path, old, git_h=2.0)
    r = D().alert_if_stale()
    assert r["status"] == "BACKUP_STALE_ALERTED"
    assert len(FakeNotifier.calls) == 1
    assert FakeNotifier.calls[0]["severity"] == "WARNING"          # NOT CRITICAL
    assert FakeNotifier.calls[0]["event_type"] == "BACKUP_FS_STALE_GIT_OK"


def test_never_backed_up_with_stale_git_is_critical(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, None, git_h=999.0)
    r = D().alert_if_stale()
    assert r["status"] == "BACKUP_STALE_ALERTED"
    assert FakeNotifier.calls[0]["severity"] == "CRITICAL"


def test_unconfirmable_git_fails_safe_to_critical(monkeypatch, tmp_path):
    # If git freshness can't be read (None), do NOT suppress — fail safe to the CRITICAL alarm.
    old = (datetime.utcnow() - timedelta(hours=30)).isoformat()
    _patch(monkeypatch, tmp_path, old, git_h=None)
    assert D().alert_if_stale()["status"] == "BACKUP_STALE_ALERTED"
    assert FakeNotifier.calls[0]["severity"] == "CRITICAL"


def test_stale_alert_is_throttled(monkeypatch, tmp_path):
    old = (datetime.utcnow() - timedelta(hours=30)).isoformat()
    _patch(monkeypatch, tmp_path, old, git_h=40.0)
    assert D().alert_if_stale()["status"] == "BACKUP_STALE_ALERTED"
    # immediate re-check within the throttle window must NOT re-alert
    assert D().alert_if_stale()["status"] == "BACKUP_STALE_THROTTLED"
    assert len(FakeNotifier.calls) == 1


# --- _run_and_alert (the sibling path the git-aware fix originally MISSED) ------------------------

def _patch_run(monkeypatch, backup_status, git_h):
    FakeNotifier.calls = []
    monkeypatch.setattr(D, "backup", lambda self, tier2=False: {"status": backup_status, "error": "x"})
    monkeypatch.setattr("app.services.operator_notification_engine.OperatorNotificationEngine",
                        lambda: FakeNotifier())
    import app.services.git_data_backup_engine as g
    monkeypatch.setattr(g.GitDataBackupEngine, "hours_since", lambda self: git_h)


def test_run_and_alert_incomplete_but_git_fresh_is_warning(monkeypatch):
    # An interrupted (INCOMPLETE) filesystem backup while the git channel is fresh = data still protected
    # -> WARNING, never the CRITICAL "data unprotected" that cried wolf before.
    _patch_run(monkeypatch, "BACKUP_INCOMPLETE", git_h=2.0)
    D()._run_and_alert()
    assert len(FakeNotifier.calls) == 1
    assert FakeNotifier.calls[0]["severity"] == "WARNING"
    assert FakeNotifier.calls[0]["event_type"] == "BACKUP_FS_INCOMPLETE_GIT_OK"


def test_run_and_alert_incomplete_and_git_stale_is_critical(monkeypatch):
    _patch_run(monkeypatch, "BACKUP_DEGRADED", git_h=99.0)
    D()._run_and_alert()
    assert len(FakeNotifier.calls) == 1
    assert FakeNotifier.calls[0]["severity"] == "CRITICAL"
    assert FakeNotifier.calls[0]["event_type"] == "BACKUP_FAILED"


def test_run_and_alert_success_is_silent(monkeypatch):
    _patch_run(monkeypatch, "BACKUP_VERIFIED", git_h=2.0)
    D()._run_and_alert()
    assert FakeNotifier.calls == []
