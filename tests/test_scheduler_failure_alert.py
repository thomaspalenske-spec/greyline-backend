"""The scheduler must make silent cycle failures LOUD — it hid a 25h/303-cycle outage on 2026-07-26.

Verifies: no alert below the threshold, an alert once the streak crosses it, a recovery alert when it
comes back, and that alerting is gated on an EXTERNAL channel (a local popup is useless if the box is
the problem). The dispatch layer handles throttling (fingerprint cooldown); this layer just decides
WHEN to call it.
"""

import app.services.background_scheduler_service as mod
import app.services.external_alert_engine as ae
from app.services.background_scheduler_service import BackgroundSchedulerService as S

NOW = "2026-07-26T18:00:00"


def _reset(monkeypatch):
    S._consecutive_failures = 0
    S._success_count = 0
    S._failure_count = 0
    S._recent_cycles = []
    monkeypatch.setattr(mod, "append_jsonl", lambda *a, **k: None)   # no heartbeat file I/O in tests


def test_no_alert_below_threshold(monkeypatch):
    _reset(monkeypatch)
    fired = []
    monkeypatch.setattr(S, "_alert_cycle_failures", classmethod(lambda cls, n, e: fired.append(n)))
    for _ in range(S._ALERT_AFTER_FAILURES - 1):
        S._record_result("FAILED", NOW, error="boom")
    assert fired == []


def test_success_clears_stale_last_error(monkeypatch):
    # last_error must reflect the LAST cycle: a COMPLETE cycle clears a prior failure so a long-since-fixed
    # error (the 2026-07-26 MarketHoursEngine bug) stops rendering as a live problem weeks later.
    _reset(monkeypatch)
    monkeypatch.setattr(S, "_alert_cycle_failures", classmethod(lambda cls, n, e: None))
    S._record_result("FAILED", NOW, error="boom")
    assert S._last_error == "boom" and S._last_error_at is not None
    S._record_result("COMPLETE", NOW)
    assert S._last_error is None and S._last_error_at is None


def test_alert_at_threshold_and_keeps_calling(monkeypatch):
    _reset(monkeypatch)
    fired = []
    monkeypatch.setattr(S, "_alert_cycle_failures", classmethod(lambda cls, n, e: fired.append(n)))
    for _ in range(S._ALERT_AFTER_FAILURES):
        S._record_result("FAILED", NOW, error="boom")
    assert fired == [S._ALERT_AFTER_FAILURES]                # first alert exactly at the crossing
    S._record_result("FAILED", NOW, error="boom")
    assert fired[-1] == S._ALERT_AFTER_FAILURES + 1          # keeps calling; dispatch dedups downstream


def test_recovery_alert_after_failing_streak(monkeypatch):
    _reset(monkeypatch)
    recovered = []
    monkeypatch.setattr(S, "_alert_cycle_failures", classmethod(lambda cls, n, e: None))
    monkeypatch.setattr(S, "_alert_cycle_recovered", classmethod(lambda cls, p: recovered.append(p)))
    for _ in range(S._ALERT_AFTER_FAILURES):
        S._record_result("FAILED", NOW, error="boom")
    S._record_result("COMPLETE", NOW)
    assert recovered == [S._ALERT_AFTER_FAILURES]
    assert S._consecutive_failures == 0


def test_no_recovery_alert_if_never_crossed_threshold(monkeypatch):
    _reset(monkeypatch)
    recovered = []
    monkeypatch.setattr(S, "_alert_cycle_recovered", classmethod(lambda cls, p: recovered.append(p)))
    S._record_result("FAILED", NOW, error="boom")            # 1 failure, below threshold
    S._record_result("COMPLETE", NOW)
    assert recovered == []


def test_alert_gated_on_external_channel(monkeypatch):
    disp = []

    class NoChannel:
        def has_external_channel(self): return False
        def dispatch(self, **k): disp.append(k)
    monkeypatch.setattr(ae, "ExternalAlertEngine", NoChannel)
    S._alert_cycle_failures(3, "boom")
    assert disp == []                                        # no external channel -> no alert

    disp2 = []

    class HasChannel:
        def has_external_channel(self): return True
        def dispatch(self, **k): disp2.append(k)
    monkeypatch.setattr(ae, "ExternalAlertEngine", HasChannel)
    S._alert_cycle_failures(3, "boom")
    assert len(disp2) == 1 and disp2[0]["severity"] == "CRITICAL"
