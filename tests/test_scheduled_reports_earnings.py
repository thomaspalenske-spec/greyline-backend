"""Earnings fire-readiness + activity lines in the scheduled operator reports (read-only helpers)."""

import app.services.earnings_vol_harvest_engine as ev_mod
import app.services.edge_persistence_engine as ep_mod
import app.services.pre_open_readiness_engine as pr_mod
from app.services.scheduled_operator_reports_engine import ScheduledOperatorReportsEngine as S


def _mock_earnings(monkeypatch, fire):
    monkeypatch.setattr(ev_mod, "EarningsVolHarvestEngine",
                        lambda: type("E", (), {"fire_readiness": lambda self: fire,
                                               "status": lambda self: {"open_positions": 2}})())


def test_pager_line_will_fire(monkeypatch):
    # WILL FIRE only when the dry-run actually confirmed a buildable condor (build_verified True).
    _mock_earnings(monkeypatch, {"will_fire": True, "build_verified": True, "report_dates": ["2026-08-03"]})
    line = S._earnings_readiness_line()
    assert "WILL FIRE" in line and "2026-08-03" in line


def test_pager_line_gates_ready_build_pending_when_unverified(monkeypatch):
    # Gates pass but the build is deferred (market closed pre-open) — must NOT overstate "WILL FIRE".
    _mock_earnings(monkeypatch, {"will_fire": True, "build_verified": False, "report_dates": ["2026-08-03"]})
    line = S._earnings_readiness_line()
    assert "WILL FIRE" not in line and "build pending" in line and "2026-08-03" in line


def test_pager_line_not_ready_gives_reason(monkeypatch):
    _mock_earnings(monkeypatch, {"will_fire": False, "verdict": "NOT READY — armed", "report_dates": []})
    line = S._earnings_readiness_line()
    assert "will NOT fire" in line and "armed" in line


def test_postclose_line_reports_court_progress(monkeypatch):
    _mock_earnings(monkeypatch, {})
    monkeypatch.setattr(ep_mod, "EdgePersistenceEngine",
                        lambda: type("P", (), {"realized_edge": lambda self: {"sleeves": {"premium_earnings": {"trades": 3}}}})())
    line = S._earnings_activity_line()
    assert "2 open condor" in line and "3 premium_earnings" in line


def test_pre_open_pager_includes_the_earnings_line(monkeypatch):
    monkeypatch.setattr(pr_mod, "PreOpenReadinessEngine",
                        lambda: type("A", (), {"audit": lambda self: {"overall": "READY", "fail_count": 0,
                                                                      "warn_count": 0, "checks": []}})())
    _mock_earnings(monkeypatch, {"will_fire": True, "build_verified": True, "report_dates": ["2026-08-03"]})
    captured = {}
    monkeypatch.setattr(S, "_dispatch",
                        lambda title, message, severity, fingerprint: captured.update(msg=message) or {"ok": True})
    S._pre_open_pager("2026-08-03")
    assert "WILL FIRE" in captured["msg"] and "READY for the open" not in captured.get("title", "")
