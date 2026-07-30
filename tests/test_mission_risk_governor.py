"""Book-level risk governor: the daily-loss ladder and deployment cap must fire CRITICAL alerts at
the right thresholds, write the halt marker on a hard breach, and throttle so it doesn't pager-storm."""

from app.services.mission_risk_governor_engine import MissionRiskGovernorEngine as G


class FakeNotifier:
    calls = []

    def record(self, **kw):
        FakeNotifier.calls.append(kw)


def _patch(mp, tmp, equity, sod, deployed):
    mp.setenv("GREYLINE_ACCOUNT_CAPITAL_BASE", "10000")
    mp.setenv("GREYLINE_DAILY_LOSS_WARN_PCT", "4")
    mp.setenv("GREYLINE_DAILY_LOSS_HALT_PCT", "7")
    mp.setattr(G, "DIR", tmp)
    mp.setattr(G, "SOD", tmp / "sod.json")
    mp.setattr(G, "HALT_MARKER", tmp / "halt.json")
    mp.setattr(G, "ALERT_STATE", tmp / "alert.json")
    mp.setattr(G, "_equity_and_deployed", lambda self: (equity, deployed, True))  # reads_ok=True
    mp.setattr(G, "_sod_equity", lambda self, cur, persist=True: sod)
    mp.setattr("app.services.operator_notification_engine.OperatorNotificationEngine",
               lambda: FakeNotifier())
    FakeNotifier.calls = []


def test_flat_book_no_alert(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, equity=10000, sod=10000, deployed=5000)
    r = G().check_and_alert()
    assert r["alerts_fired"] == [] and FakeNotifier.calls == []


def test_warn_line_fires_warning(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, equity=9550, sod=10000, deployed=5000)   # -450 = -4.5% <= -4%
    r = G().check_and_alert()
    assert "WARN" in r["alerts_fired"]
    assert FakeNotifier.calls and FakeNotifier.calls[0]["severity"] == "WARNING"
    assert not G().opens_halted()                                         # warn does NOT halt


def test_halt_line_fires_critical_and_marks_halt(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, equity=9250, sod=10000, deployed=5000)   # -750 = -7.5% <= -7%
    r = G().check_and_alert()
    assert "HALT" in r["alerts_fired"]
    assert FakeNotifier.calls[0]["severity"] == "CRITICAL"
    assert G().opens_halted() is True                                     # marker written for today


def test_over_deployment_fires_critical(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, equity=10000, sod=10000, deployed=11000)  # 110% of book
    r = G().check_and_alert()
    assert "OVER_DEPLOYED" in r["alerts_fired"]
    assert any(c["severity"] == "CRITICAL" for c in FakeNotifier.calls)


def test_broker_read_failure_fires_no_false_alerts(monkeypatch, tmp_path):
    """A FAILED broker read (reads_ok=False) must NOT be treated as $0 deployed / a huge loss.
    Even with a -50% daily P&L and 0% deployed on the read, the loss-ladder and armed-idle checks
    are SKIPPED — acting on a zeroed read would false-page the operator mid-open."""
    _patch(monkeypatch, tmp_path, equity=5000, sod=10000, deployed=0)   # would be HALT + idle if trusted
    monkeypatch.setattr(G, "_equity_and_deployed", lambda self: (5000, 0, False))  # reads_ok=False
    monkeypatch.setattr(G, "_armed", classmethod(lambda cls: ["GREYLINE_TREND_ENABLED"]))
    monkeypatch.setattr(G, "_is_rth", lambda self: True)
    r = G().check_and_alert()
    assert r["alerts_fired"] == []                       # no HALT, no ARMED_IDLE, no OVER_DEPLOYED
    assert r.get("skipped") == "broker_read_degraded"
    assert FakeNotifier.calls == []
    assert not G().opens_halted()                        # no halt marker written on a bad read


def test_armed_but_idle_fires_critical(monkeypatch, tmp_path):
    """The silent open-day failure: strategies enabled, market open, deployed ~0 for too long."""
    from datetime import datetime, timedelta
    _patch(monkeypatch, tmp_path, equity=10000, sod=10000, deployed=0)         # 0% deployed
    monkeypatch.setattr(G, "_armed", classmethod(lambda cls: ["GREYLINE_TREND_ENABLED"]))
    monkeypatch.setattr(G, "_is_rth", lambda self: True)
    monkeypatch.setattr(G, "_idle_since", lambda self: datetime.utcnow() - timedelta(minutes=25))
    r = G().check_and_alert()
    assert "ARMED_IDLE" in r["alerts_fired"]
    assert any(c["severity"] == "CRITICAL" for c in FakeNotifier.calls)


def test_armed_and_deployed_is_not_idle(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, equity=10000, sod=10000, deployed=4000)      # 40% deployed
    monkeypatch.setattr(G, "_armed", classmethod(lambda cls: ["GREYLINE_TREND_ENABLED"]))
    monkeypatch.setattr(G, "_is_rth", lambda self: True)
    assert "ARMED_IDLE" not in G().check_and_alert()["alerts_fired"]


def test_idle_but_not_armed_is_silent(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, equity=10000, sod=10000, deployed=0)         # flat but nothing armed
    monkeypatch.setattr(G, "_armed", classmethod(lambda cls: []))
    monkeypatch.setattr(G, "_is_rth", lambda self: True)
    assert "ARMED_IDLE" not in G().check_and_alert()["alerts_fired"]


def test_alert_is_throttled(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, equity=9550, sod=10000, deployed=5000)
    assert G().check_and_alert()["alerts_fired"] == ["WARN"]
    assert G().check_and_alert()["alerts_fired"] == []                    # throttled within the window
    assert len(FakeNotifier.calls) == 1
