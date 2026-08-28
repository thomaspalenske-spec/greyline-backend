"""Condor mark-health guard — makes a hidden mark LOUD so the RBLX class can never recur silently.
#2 persistent-unpriced (>=2 market-days, RTH-only accrual); #3 contradiction (gain while past a wing)."""

import pytest

from app.services.condor_shadow_engine import CondorShadowEngine as C

_LEGS = {"short_call": {"strike": 70.0}, "wing_call": {"strike": 72.5},
         "short_put": {"strike": 42.5}, "wing_put": {"strike": 40.0}}


def _entry(sym="X"):
    return {"id": sym, "symbol": sym, "expiration": "2026-09-18", "status": "OPEN", "legs": _LEGS}


@pytest.fixture(autouse=True)
def _tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "MARK_HEALTH", tmp_path / "mh.json")
    monkeypatch.setattr("app.services.shadow_tradeability_gate.equity_session_open", lambda: True)  # RTH
    yield


def test_persistent_unpriced_flags_after_two_market_days(monkeypatch):
    monkeypatch.setattr(C, "_entries", lambda self: [_entry("X")])
    monkeypatch.setattr(C, "open_positions", lambda self: [{"symbol": "X", "expiration": "2026-09-18"}])  # no current_value
    monkeypatch.setattr(C, "_et_date", lambda self: "2026-08-27")
    assert C().mark_health()["persistent_unpriced"] == []          # day 1 only — quiet
    monkeypatch.setattr(C, "_et_date", lambda self: "2026-08-28")
    h = C().mark_health()
    assert any(p["symbol"] == "X" for p in h["persistent_unpriced"])   # day 2 — flagged
    assert h["ok"] is False


def test_after_hours_unpriced_never_accrues(monkeypatch):
    monkeypatch.setattr("app.services.shadow_tradeability_gate.equity_session_open", lambda: False)  # market closed
    monkeypatch.setattr(C, "_entries", lambda self: [_entry("X")])
    monkeypatch.setattr(C, "open_positions", lambda self: [{"symbol": "X", "expiration": "2026-09-18"}])
    monkeypatch.setattr(C, "_et_date", lambda self: "2026-08-27")
    C().mark_health()
    monkeypatch.setattr(C, "_et_date", lambda self: "2026-08-28")
    assert C().mark_health()["persistent_unpriced"] == []          # expected after-hours gap, no false alarm


def test_contradiction_gain_while_past_a_wing(monkeypatch):
    monkeypatch.setattr(C, "_entries", lambda self: [_entry("Y")])
    monkeypatch.setattr(C, "open_positions",
                        lambda self: [{"symbol": "Y", "expiration": "2026-09-18", "current_value": 0.1, "pnl_dollars": 50.0}])
    monkeypatch.setattr(C, "_underlying_spot", lambda self, s: 39.0)  # below wing_put 40 -> past put wing
    monkeypatch.setattr(C, "_et_date", lambda self: "2026-08-28")
    h = C().mark_health()
    assert any(c["symbol"] == "Y" for c in h["contradictions"])
    assert h["ok"] is False


def test_clean_book_is_ok(monkeypatch):
    monkeypatch.setattr(C, "_entries", lambda self: [_entry("Z")])
    monkeypatch.setattr(C, "open_positions",
                        lambda self: [{"symbol": "Z", "expiration": "2026-09-18", "current_value": 0.2, "pnl_dollars": 30.0}])
    monkeypatch.setattr(C, "_underlying_spot", lambda self, s: 55.0)  # in band, priced, gain — consistent
    monkeypatch.setattr(C, "_et_date", lambda self: "2026-08-28")
    assert C().mark_health()["ok"] is True
