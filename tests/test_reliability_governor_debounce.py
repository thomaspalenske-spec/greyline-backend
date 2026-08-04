"""Reliability governor debounce: a SINGLE transient broker-side blip (quote heartbeat / TS token) must
NOT flip GREEN->SAFE_MODE and page CRITICAL (the cry-wolf a saturated cycle produced). It is RECOMMEND_ONLY
until it PERSISTS, then escalates to SAFE_MODE. Structural failures still SAFE_MODE immediately, and
execution stays blocked in every degraded mode (this only changes the alarm severity, never loosens exec)."""

import app.services.reliability_governor_engine as mod
from app.services.reliability_governor_engine import ReliabilityGovernorEngine as G


def _wire(monkeypatch, tmp_path, *, health_ok=True, sched_ok=True, quote_ok=True, token_ok=True):
    monkeypatch.setattr(G, "STATE_FILE", tmp_path / "state.json")

    class _H:
        def status(self):
            return {"overall_health": "GREEN" if health_ok else "RED",
                    "red_count": 0 if health_ok else 1, "checks": []}

    class _S:
        @staticmethod
        def status():
            return {"thread_alive": sched_ok, "last_status": "X"}

    class _Q:
        @staticmethod
        def status():
            return {"status": "FAST_QUOTE_HEARTBEAT_STATUS_READY" if quote_ok else "STALE"}

    class _T:
        def evaluate(self):
            return {"ready_for_read_only": token_ok}

    monkeypatch.setattr("app.services.system_health_dashboard_engine.SystemHealthDashboardEngine", _H)
    monkeypatch.setattr("app.services.background_scheduler_service.BackgroundSchedulerService", _S)
    monkeypatch.setattr("app.services.fast_quote_heartbeat_service.FastQuoteHeartbeatService", _Q)
    monkeypatch.setattr("app.services.tradestation_token_status_engine.TradeStationTokenStatusEngine", _T)
    # silence the event bus so a mode change doesn't try to page in tests
    monkeypatch.setattr(mod.OperatorEventBusEngine, "publish", lambda self, **k: None)


def test_all_healthy_is_paper_operational(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    r = G().evaluate()
    assert r["operating_mode"] == "PAPER_OPERATIONAL" and r["execution_allowed"] is True


def test_single_transient_blip_is_recommend_only_not_safe_mode(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, token_ok=False)         # one transient check down, structure healthy
    r = G().evaluate()
    assert r["operating_mode"] == "RECOMMEND_ONLY"        # NOT SAFE_MODE
    assert r["execution_allowed"] is False                # still blocked — no loosening
    assert r["transient_fail_streak"] == 1


def test_persistent_transient_escalates_to_safe_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("GREYLINE_RELIABILITY_TRANSIENT_STREAK", "3")
    for i in range(1, 4):
        _wire(monkeypatch, tmp_path, quote_ok=False)     # keep the blip failing
        r = G().evaluate()
    assert r["transient_fail_streak"] == 3
    assert r["operating_mode"] == "SAFE_MODE"             # escalated once it persisted


def test_structural_failure_is_safe_mode_immediately(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, sched_ok=False)         # scheduler down = structural, no debounce
    r = G().evaluate()
    assert r["operating_mode"] == "SAFE_MODE"


def test_transient_recovery_resets_streak(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, token_ok=False)
    assert G().evaluate()["transient_fail_streak"] == 1
    _wire(monkeypatch, tmp_path)                          # recovered
    r = G().evaluate()
    assert r["transient_fail_streak"] == 0 and r["operating_mode"] == "PAPER_OPERATIONAL"
