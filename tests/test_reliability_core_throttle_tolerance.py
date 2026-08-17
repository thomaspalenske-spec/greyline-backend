"""The reliability core must not flap Mission Status to DEGRADED on a transient broker THROTTLE.

A 429 is a rate-limit ("you're calling too often"), not a broker/auth outage or fabricated data, and it
self-clears — while token + positions still confirm the account is live and authed. So a 429 on the
balance (or positions) read is treated as verified-hold, NOT a reliability failure. A REAL failure
(auth 401/403, server 5xx, empty body) still degrades.
"""

import app.services.greyline_reliability_core_engine as mod
from app.services.greyline_reliability_core_engine import GreyLineReliabilityCoreEngine as C


def _env(monkeypatch, balance=None, positions=None):
    monkeypatch.setattr(mod.TradeStationTokenStatusEngine, "evaluate",
                        lambda self: {"ready_for_read_only": True})
    monkeypatch.setattr(mod.TradeStationBalanceLiveEngine, "get_balance",
                        lambda self: balance or {"status": "BALANCE_READ_SUCCESS", "http_status": 200})
    monkeypatch.setattr(mod.TradeStationPositionsLiveEngine, "get_positions",
                        lambda self: positions or {"status": "POSITIONS_READ_SUCCESS", "http_status": 200,
                                                   "response_json": {"Positions": []}})
    monkeypatch.setattr(mod.OptionsAccountDashboardEngine, "get_dashboard",
                        lambda self: {"open_option_trade_count": 0, "account_type": "paper", "open_positions": []})
    monkeypatch.setattr(mod.BackgroundSchedulerService, "status",
                        lambda: {"thread_alive": True, "scheduler_enabled": True, "cycle_count": 1})
    monkeypatch.setattr(mod.ExecutionGovernor, "evaluate_execution_permission",
                        lambda self, sig: {"execution_enabled": True, "order_placement_allowed": False})


def test_balance_429_holds_healthy(monkeypatch):
    _env(monkeypatch, balance={"status": "BALANCE_READ_FAILED", "http_status": 429})
    r = C().evaluate()
    assert r["status"] == "RELIABILITY_CORE_HEALTHY" and r["health_score"] == 100
    assert r["checks"]["balance_ok"] is True
    assert r["broker_truth"]["balance_read_state"] == "throttled"


def test_positions_429_holds_healthy(monkeypatch):
    _env(monkeypatch, positions={"status": "POSITIONS_READ_FAILED", "http_status": 429, "response_json": {}})
    r = C().evaluate()
    assert r["status"] == "RELIABILITY_CORE_HEALTHY" and r["health_score"] == 100
    assert r["broker_truth"]["positions_read_state"] == "throttled"


def test_balance_real_failure_degrades(monkeypatch):
    _env(monkeypatch, balance={"status": "BALANCE_READ_FAILED", "http_status": 500})
    r = C().evaluate()
    assert r["status"] == "RELIABILITY_CORE_DEGRADED"
    assert r["checks"]["balance_ok"] is False
    assert r["broker_truth"]["balance_read_state"] == "failed"


def test_balance_auth_failure_degrades(monkeypatch):
    _env(monkeypatch, balance={"status": "BALANCE_READ_FAILED", "http_status": 401})
    r = C().evaluate()
    assert r["status"] == "RELIABILITY_CORE_DEGRADED" and r["checks"]["balance_ok"] is False


def test_all_success_is_healthy(monkeypatch):
    _env(monkeypatch)
    r = C().evaluate()
    assert r["status"] == "RELIABILITY_CORE_HEALTHY"
    assert r["broker_truth"]["balance_read_state"] == "success"
