"""EdgePersistenceEngine v2 — the realized-trade edge court. Verdicts come from CLOSED trades,
cost-net, with a 95% CI and a minimum-sample gate. Forced/administrative closes are excluded, and
autocorrelated daily open-marks are NEVER used for a verdict. Fully hermetic — no broker, no orders."""

import json

from app.services.edge_persistence_engine import EdgePersistenceEngine as E


def _trades(n, net, risk=100.0, sleeve="premium", basis="fill_net"):
    return [{"sleeve": sleeve, "gross": net, "net": net, "risk": risk,
             "closed_at": "2026-07-31T00:00:00", "basis": basis} for _ in range(n)]


def _verdict(monkeypatch, trades):
    monkeypatch.setattr(E, "_closed_trades", lambda self: (trades, 0))
    out = E().realized_edge()
    return out["sleeves"].get("premium", {}), out


def test_too_few_trades_is_accumulating(monkeypatch):
    stat, _ = _verdict(monkeypatch, _trades(5, 10.0))
    assert stat["trades"] == 5 and "ACCUMULATING" in stat["verdict"]


def test_consistent_winners_prove_the_edge(monkeypatch):
    # 24 trades, small spread around +$10 on $100 risk -> tight CI well above 0
    trades = [{"sleeve": "premium", "gross": v, "net": v, "risk": 100.0,
               "closed_at": "x", "basis": "fill_net"} for v in ([9.0, 11.0] * 12)]
    stat, _ = _verdict(monkeypatch, trades)
    assert "PROVEN" in stat["verdict"]
    assert stat["ci95_return_on_risk_pct"][0] > 0        # CI lower bound above zero
    assert stat["mean_return_on_risk_pct"] == 10.0


def test_consistent_losers_are_decayed(monkeypatch):
    trades = [{"sleeve": "premium", "gross": v, "net": v, "risk": 100.0,
               "closed_at": "x", "basis": "fill_net"} for v in ([-9.0, -11.0] * 12)]
    stat, _ = _verdict(monkeypatch, trades)
    assert "DECAYED" in stat["verdict"] and stat["ci95_return_on_risk_pct"][1] < 0


def test_noisy_zero_mean_is_unproven(monkeypatch):
    trades = [{"sleeve": "premium", "gross": v, "net": v, "risk": 100.0,
               "closed_at": "x", "basis": "fill_net"} for v in ([50.0, -50.0] * 12)]
    stat, _ = _verdict(monkeypatch, trades)
    assert "UNPROVEN" in stat["verdict"]
    lo, hi = stat["ci95_return_on_risk_pct"]
    assert lo < 0 < hi                                    # CI straddles zero


def test_closest_to_proven_ranks_by_t_stat(monkeypatch):
    strong = _trades(24, 10.0, sleeve="premium")
    weak = [{"sleeve": "momentum", "gross": v, "net": v, "risk": 100.0, "closed_at": "x",
             "basis": "fill_net"} for v in ([1.0, -1.0] * 12)]
    monkeypatch.setattr(E, "_closed_trades", lambda self: (strong + weak, 0))
    out = E().realized_edge()
    assert out["closest_to_proven"][0]["sleeve"] == "premium"   # higher t-stat ranked first


def test_forced_and_admin_closes_excluded(tmp_path, monkeypatch):
    vrp = tmp_path / "vrp.jsonl"
    eq = tmp_path / "eq.jsonl"
    vrp.write_text("\n".join(json.dumps(r) for r in [
        {"status": "CLOSED", "close_reason": "profit-take", "realized_pnl": 40.0, "max_loss_total": 300.0},
        {"status": "CLOSED", "close_reason": "CLEAN_SLATE_FLATTEN", "realized_pnl": 0.0, "max_loss_total": 300.0},
    ]) + "\n")
    eq.write_text("\n".join(json.dumps(r) for r in [
        {"status": "CLOSED", "close_reason": "ACCOUNT_RESET", "realized_pnl": 0.0,
         "asset_type": "EQUITY", "entry_price": 100.0, "quantity": 5, "symbol": "GLW"},
        {"status": "CLOSED", "close_reason": "TP1 hit", "realized_pnl": 25.0,
         "asset_type": "EQUITY", "entry_price": 100.0, "quantity": 5, "symbol": "GLW"},
    ]) + "\n")
    monkeypatch.setattr(E, "VRP_LEDGER", vrp)
    monkeypatch.setattr(E, "EQ_LEDGER", eq)
    monkeypatch.setattr(E, "OPT_LEDGER", tmp_path / "none.jsonl")
    trades, excluded = E()._closed_trades()
    assert excluded == 2                                    # the flatten + the reset
    sleeves = {t["sleeve"] for t in trades}
    assert sleeves == {"premium", "momentum"}              # only the two real strategy exits
    # the condor (mid_estimate) is haircut 3% of max-loss: net = 40 - 0.03*300 = 31
    prem = next(t for t in trades if t["sleeve"] == "premium")
    assert prem["net"] == 31.0 and prem["basis"] == "mid_estimate"
    # the equity fill is already net (no extra haircut)
    eqt = next(t for t in trades if t["sleeve"] == "momentum")
    assert eqt["net"] == 25.0 and eqt["basis"] == "fill_net"
