"""Decayed-sleeve retirement alert: when the edge court judges a sleeve DECAYED (cost-net edge < 0 at
95%, >= gate), page (deduped) and flag it on the Reality Guard. The RETIRE half of measure->retire."""

from app.services.edge_persistence_engine import EdgePersistenceEngine as E
from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G


def _court(monkeypatch, sleeves):
    monkeypatch.setattr(E, "realized_edge", lambda self: {"sleeves": sleeves})


def test_decay_alert_quiet_when_healthy(monkeypatch):
    _court(monkeypatch, {"premium_vrp": {"verdict": "PROVEN — cost-net edge > 0 at 95% confidence", "trades": 25}})
    r = E().decay_alert(dispatch=False)
    assert r["status"] == "EDGE_DECAY_NONE" and r["decayed"] == []


def test_decay_alert_flags_decayed_sleeve(monkeypatch):
    _court(monkeypatch, {
        "premium_earnings": {"verdict": "DECAYED — cost-net edge < 0 at 95% confidence; retire",
                             "trades": 22, "mean_return_on_risk_pct": -3.1, "ci95_return_on_risk_pct": [-5.0, -1.2]},
        "trend": {"verdict": "ACCUMULATING (4/20 trades — too few to judge)", "trades": 4}})
    sent = {}
    import app.services.external_alert_engine as ae_mod
    monkeypatch.setattr(ae_mod, "ExternalAlertEngine", lambda: type("A", (), {
        "has_external_channel": lambda self: True,
        "dispatch": lambda self, **k: sent.update(k)})())
    r = E().decay_alert(dispatch=True)
    assert r["status"] == "EDGE_DECAY_FLAGGED" and r["decayed"] == ["premium_earnings"]
    assert "DECAYED" in sent["title"] and sent["fingerprint"] == "EDGE_DECAYED:premium_earnings"  # stable dedup key
    assert "premium_earnings" in sent["message"]


def test_reality_guard_surfaces_decayed(monkeypatch):
    _court(monkeypatch, {"premium_vrp": {"verdict": "DECAYED — cost-net edge < 0 at 95% confidence; retire",
                                         "trades": 20}})
    inv = G()._check_sleeve_edge_not_decayed()
    assert inv["id"] == "EDGE_NOT_DECAYED" and inv["ok"] is False and "premium_vrp" in inv["detail"]


def test_reality_guard_ok_when_none_decayed(monkeypatch):
    _court(monkeypatch, {"trend": {"verdict": "ACCUMULATING (0/20 trades)", "trades": 0}})
    inv = G()._check_sleeve_edge_not_decayed()
    assert inv["ok"] is True
