"""External alerting — a CRITICAL event must be able to LEAVE the machine, and the system must
be HONEST when it cannot. The proof case: a silent backfill failure that reported 'complete'."""

import os


def _clear_channels(monkeypatch):
    for k in ("GREYLINE_ALERT_WEBHOOK_URL", "GREYLINE_ALERT_NTFY_TOPIC"):
        monkeypatch.delenv(k, raising=False)


def test_no_channel_is_reported_honestly_not_as_success(monkeypatch):
    from app.services.external_alert_engine import ExternalAlertEngine
    _clear_channels(monkeypatch)
    monkeypatch.setenv("GREYLINE_ALERT_MACOS_LOCAL", "false")  # no on-machine either, for clarity
    e = ExternalAlertEngine()
    assert e.has_external_channel() is False
    r = e.dispatch("x", "y", severity="CRITICAL", force=True)
    assert r["status"] == "ALERT_STAYED_ON_MACHINE"
    assert r["reached_off_machine"] is False
    assert "did NOT leave the machine" in r["warning"]


def test_status_names_configured_external_channels(monkeypatch):
    from app.services.external_alert_engine import ExternalAlertEngine
    _clear_channels(monkeypatch)
    monkeypatch.setenv("GREYLINE_ALERT_NTFY_TOPIC", "greyline-secret-topic-123")
    s = ExternalAlertEngine().status()
    assert s["has_external_channel"] is True
    assert "ntfy" in s["external_channels"]


def test_macos_local_is_never_counted_as_off_machine(monkeypatch):
    from app.services.external_alert_engine import ExternalAlertEngine
    _clear_channels(monkeypatch)
    monkeypatch.setenv("GREYLINE_ALERT_MACOS_LOCAL", "true")
    e = ExternalAlertEngine()
    # macOS local is on-machine convenience only; it must not make has_external_channel() true
    assert e.has_external_channel() is False


def test_cooldown_suppresses_a_pager_storm(monkeypatch, tmp_path):
    from app.services.external_alert_engine import ExternalAlertEngine
    _clear_channels(monkeypatch)
    monkeypatch.setenv("GREYLINE_ALERT_NTFY_TOPIC", "t")
    e = ExternalAlertEngine()
    e.STATE = tmp_path / "state.json"
    sent = {"n": 0}

    def fake_ntfy(title, message, severity):
        sent["n"] += 1
        return {"channel": "ntfy", "ok": True}

    monkeypatch.setattr(e, "_send_ntfy", fake_ntfy)
    monkeypatch.setattr(e, "_send_macos", lambda *a, **k: None)
    r1 = e.dispatch("same", "cond", severity="CRITICAL", fingerprint="fp1")
    r2 = e.dispatch("same", "cond", severity="CRITICAL", fingerprint="fp1")
    assert r1["reached_off_machine"] is True
    assert r2["status"] == "SUPPRESSED_COOLDOWN"
    assert sent["n"] == 1, "identical condition paged twice — cooldown failed"


def test_critical_notification_auto_escalates(monkeypatch, tmp_path):
    """record(severity=CRITICAL) must trigger an external dispatch; INFO must not."""
    from app.services.operator_notification_engine import OperatorNotificationEngine
    import app.services.external_alert_engine as ext

    calls = {"n": 0}

    class FakeAlert:
        def dispatch(self, **kw):
            calls["n"] += 1
            return {"status": "ALERT_STAYED_ON_MACHINE"}

    monkeypatch.setattr(ext, "ExternalAlertEngine", FakeAlert)
    eng = OperatorNotificationEngine()
    eng.ledger_file = tmp_path / "n.jsonl"

    eng.record("TEST", "info event", "msg", severity="INFO")
    assert calls["n"] == 0
    out = eng.record("BACKUP_FAILED", "boom", "msg", severity="CRITICAL")
    assert calls["n"] == 1
    assert out["external_alert"]["status"] == "ALERT_STAYED_ON_MACHINE"


def test_guard_flags_missing_external_channel(monkeypatch):
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine
    _clear_channels(monkeypatch)
    chk = GreyLineRealityGuardEngine()._check_external_alerting()
    assert chk["id"] == "EXTERNAL_ALERTING"
    assert chk["severity"] == "warning" and chk["ok"] is False
    monkeypatch.setenv("GREYLINE_ALERT_NTFY_TOPIC", "abc")
    chk2 = GreyLineRealityGuardEngine()._check_external_alerting()
    assert chk2["ok"] is True


def test_imessage_counts_as_external_and_dispatches(monkeypatch, tmp_path):
    """iMessage reaches the operator's phone, so it must count as an external channel and a
    successful send must register as reaching off-machine."""
    from app.services.external_alert_engine import ExternalAlertEngine
    _clear_channels(monkeypatch)
    monkeypatch.delenv("GREYLINE_ALERT_IMESSAGE_TO", raising=False)
    monkeypatch.setenv("GREYLINE_ALERT_IMESSAGE_TO", "+15555550123")
    e = ExternalAlertEngine()
    e.STATE = tmp_path / "state.json"
    assert e.has_external_channel() is True
    assert "imessage" in e.external_channels()

    sent = {}

    def fake_send(to_title, message, severity):
        sent["hit"] = True
        return {"channel": "imessage", "ok": True}

    monkeypatch.setattr(e, "_send_imessage", fake_send)
    monkeypatch.setattr(e, "_send_macos", lambda *a, **k: None)
    r = e.dispatch("boom", "the thing broke", severity="CRITICAL", force=True)
    assert sent.get("hit") is True
    assert r["reached_off_machine"] is True
    assert r["status"] == "ALERT_DELIVERED_OFF_MACHINE"


def test_imessage_send_never_raises_on_osascript_failure(monkeypatch):
    """A failing Messages send must be reported, never raised — an alert path must not crash the
    thing it is warning about."""
    from app.services.external_alert_engine import ExternalAlertEngine
    _clear_channels(monkeypatch)
    monkeypatch.setenv("GREYLINE_ALERT_IMESSAGE_TO", "not-a-real-buddy")

    class Boom:
        returncode = 1
        stderr = "no iMessage account"

    monkeypatch.setattr("subprocess.run", lambda *a, **k: Boom())
    r = ExternalAlertEngine()._send_imessage("t", "m", "CRITICAL")
    assert r["channel"] == "imessage" and r["ok"] is False
    assert "no iMessage account" in r["error"]
