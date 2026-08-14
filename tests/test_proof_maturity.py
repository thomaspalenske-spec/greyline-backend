"""Proof-maturity view: each edge sleeve's distance to its verdict gate + ETA. Built on realized_edge()
(the court stays the source of truth); this only projects distance-to-gate. Hermetic — court is mocked.
"""
from datetime import datetime

from app.services.edge_persistence_engine import EdgePersistenceEngine


def _engine(monkeypatch, sleeves, closed=None):
    e = EdgePersistenceEngine()
    monkeypatch.setattr(e, "realized_edge", lambda: {
        "sleeves": sleeves, "min_trades_gate": 20, "periodic_gate": 20})
    monkeypatch.setattr(e, "_closed_trades", lambda: (closed or [], 0))
    return e


def test_close_based_progress_and_eta(monkeypatch):
    # 4 independent days accrued over 8 calendar days -> rate 0.5/day -> (20-4)/0.5 = 32 days to gate
    e = _engine(monkeypatch,
                {"xs_momentum": {"trades": 4, "verdict": "ACCUMULATING (4/20 ...)",
                                 "mean_return_on_risk_pct": 1.2}},
                closed=[{"sleeve": "xs_momentum", "closed_at": "2026-08-06T00:00:00"}])
    pm = e.proof_maturity(now=datetime(2026, 8, 14))
    row = next(r for r in pm["sleeves"] if r["sleeve"] == "xs_momentum")
    assert row["current"] == 4 and row["gate"] == 20 and row["progress_pct"] == 20.0
    assert row["state"] == "ACCUMULATING"
    assert row["eta_days_to_gate"] == 32


def test_periodic_eta_is_deterministic(monkeypatch):
    # trend is periodic (cadence 7d); 5/20 periods -> (20-5)*7 = 105 days, deterministic
    e = _engine(monkeypatch, {"trend": {"trades": 5, "verdict": "ACCUMULATING (5/20 periods)"}})
    pm = e.proof_maturity(now=datetime(2026, 8, 14))
    row = next(r for r in pm["sleeves"] if r["sleeve"] == "trend")
    assert row["measure"] == "periodic"
    assert row["eta_days_to_gate"] == 105 and row["eta_confidence"].startswith("deterministic")


def test_vrp_shows_pending_when_absent(monkeypatch):
    # premium_vrp not yet in the court (0 closes) must still appear, as pending/not-estimable
    e = _engine(monkeypatch, {"xs_momentum": {"trades": 2, "verdict": "ACCUMULATING"}})
    pm = e.proof_maturity(now=datetime(2026, 8, 14))
    vrp = next(r for r in pm["sleeves"] if r["sleeve"] == "premium_vrp")
    assert vrp["current"] == 0 and vrp["eta_days_to_gate"] is None
    assert "not estimable" in vrp["eta_confidence"]


def test_proven_and_decayed_states_and_nearest(monkeypatch):
    e = _engine(monkeypatch, {
        "vol_carry": {"trades": 22, "verdict": "PROVEN — cost-net edge > 0", "mean_return_on_risk_pct": 5.0},
        "low_vol": {"trades": 21, "verdict": "DECAYED — cost-net edge < 0", "mean_return_on_risk_pct": -4.0},
        "xs_momentum": {"trades": 10, "verdict": "ACCUMULATING (10/20 ...)"},
    }, closed=[{"sleeve": "xs_momentum", "closed_at": "2026-08-09T00:00:00"}])
    pm = e.proof_maturity(now=datetime(2026, 8, 14))
    assert pm["summary"]["proven"] == ["vol_carry"]
    assert pm["summary"]["decayed"] == ["low_vol"]
    # nearest-to-verdict considers only still-accumulating sleeves
    assert pm["summary"]["nearest_to_verdict"]["sleeve"] == "xs_momentum"
