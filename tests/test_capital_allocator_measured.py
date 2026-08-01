"""Capital follows the MEASURED court verdict once a sleeve is gated: PROVEN funds it, DECAYED zeroes
it, UNPROVEN drops it to a probe; below the gate the backtest prior stands (backward-compatible)."""

import app.services.edge_persistence_engine as ep_mod
from app.services.capital_allocator_engine import CapitalAllocatorEngine as C


def _court(monkeypatch, sleeves, gate=20):
    monkeypatch.setattr(ep_mod.EdgePersistenceEngine, "realized_edge",
                        lambda self: {"min_trades_gate": gate, "sleeves": sleeves})
    monkeypatch.setattr(ep_mod.EdgePersistenceEngine, "report",
                        lambda self: {"open_drift": {}})       # keep _basis on priors


def test_no_gated_verdicts_uses_priors(monkeypatch):
    _court(monkeypatch, {})                                    # nothing gated -> unchanged
    out = C().recommend()
    assert out["measured_sleeves"] == []
    assert all(s["basis"] == "prior" for s in out["sleeves"].values())
    assert out["sleeves"]["momentum"]["recommended_usd"] == 0   # prior: no-edge -> 0


def test_proven_sleeve_gets_funded_over_prior(monkeypatch):
    # earnings prior is evidence 0 (probe); a PROVEN court verdict should fund it as a real sleeve
    _court(monkeypatch, {"premium_earnings": {"trades": 22,
           "verdict": "PROVEN — cost-net edge > 0 at 95% confidence"}})
    out = C().recommend()
    assert "earnings" in out["measured_sleeves"]
    assert out["sleeves"]["earnings"]["basis"] == "measured_proven"
    assert out["sleeves"]["earnings"]["recommended_usd"] >= C.MIN_SLEEVE_USD  # funded, not a bare probe


def test_decayed_sleeve_zeroed(monkeypatch):
    # trend prior is a funded evidence-2 sleeve; a DECAYED verdict must zero it (retire)
    _court(monkeypatch, {"trend": {"trades": 25, "verdict": "DECAYED — cost-net edge < 0 at 95%; retire"}})
    out = C().recommend()
    assert out["sleeves"]["trend"]["basis"] == "measured_decayed"
    assert out["sleeves"]["trend"]["recommended_usd"] == 0


def test_below_gate_verdict_ignored(monkeypatch):
    _court(monkeypatch, {"trend": {"trades": 5, "verdict": "ACCUMULATING (5/20 trades)"}})
    out = C().recommend()
    assert out["measured_sleeves"] == []                       # under gate -> prior stands
    assert out["sleeves"]["trend"]["basis"] == "prior"
