"""Evidence-based allocator: the no-edge sleeve goes to ~0, the book concentrates in the measured
edges, it respects the risk-on budget and ceiling, and it only ever RECOMMENDS (never mutates)."""

from app.services.capital_allocator_engine import CapitalAllocatorEngine as A


def _rec(monkeypatch):
    monkeypatch.setattr(A, "_equity", lambda self: 10000.0)
    monkeypatch.setattr(A, "_basis", lambda self: ("backtest_priors", 1))
    return A().recommend()


def test_momentum_goes_to_zero_on_no_edge(monkeypatch):
    r = _rec(monkeypatch)
    assert r["sleeves"]["momentum"]["recommended_usd"] == 0.0        # evidence -1 -> $0


def test_edges_get_the_bulk(monkeypatch):
    r = _rec(monkeypatch)["sleeves"]
    # the two backtested sleeves outweigh the unproven/no-edge ones
    assert r["trend"]["recommended_usd"] >= r["carry"]["recommended_usd"] > r["earnings"]["recommended_usd"]
    assert r["earnings"]["recommended_usd"] >= r["momentum"]["recommended_usd"]


def test_respects_risk_on_budget_and_ceiling(monkeypatch):
    r = _rec(monkeypatch)
    risk_on = sum(v["recommended_usd"] for v in r["sleeves"].values())
    assert risk_on <= 0.60 * 10000                                   # ~55% target, not the whole book
    assert all(v["recommended_pct"] <= 35.0 for v in r["sleeves"].values())   # no sleeve dominates
    assert r["tbill_cash_residual_usd"] > 0                          # real cash floor remains


def test_is_recommendation_only(monkeypatch):
    r = _rec(monkeypatch)
    assert r["status"] == "CAPITAL_ALLOCATOR_RECOMMENDATION"
    assert "does not change allocations or trade" in r["note"]
