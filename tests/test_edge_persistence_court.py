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
    assert sleeves == {"premium_vrp", "momentum"}         # VRP condor (untagged) + the equity exit
    # the condor (mid_estimate) is haircut 3% of max-loss: net = 40 - 0.03*300 = 31
    prem = next(t for t in trades if t["sleeve"] == "premium_vrp")
    assert prem["net"] == 31.0 and prem["basis"] == "mid_estimate"
    # the equity fill is already net (no extra haircut)
    eqt = next(t for t in trades if t["sleeve"] == "momentum")
    assert eqt["net"] == 25.0 and eqt["basis"] == "fill_net"


def test_earnings_and_vrp_condors_get_separate_verdicts(tmp_path, monkeypatch):
    """Earnings-vol (event IV-crush) and VRP (unconditional variance premium) share the ledger but are
    DISTINCT edges — the court must verdict them separately so one can't mask the other."""
    vrp = tmp_path / "vrp.jsonl"
    vrp.write_text("\n".join(json.dumps(r) for r in [
        {"status": "CLOSED", "close_reason": "PROFIT_TAKE_50PCT", "realized_pnl": 40.0,
         "max_loss_total": 300.0, "realized_pnl_basis": "fills"},                       # VRP (untagged)
        {"status": "CLOSED", "close_reason": "EARNINGS_CRUSH_CAPTURED", "realized_pnl": 55.0,
         "max_loss_total": 300.0, "realized_pnl_basis": "fills", "strategy": "earnings_vol"},
    ]) + "\n")
    monkeypatch.setattr(E, "VRP_LEDGER", vrp)
    monkeypatch.setattr(E, "EQ_LEDGER", tmp_path / "none.jsonl")
    monkeypatch.setattr(E, "OPT_LEDGER", tmp_path / "none2.jsonl")
    out = E().realized_edge()
    assert set(out["sleeves"]) == {"premium_vrp", "premium_earnings"}   # two distinct verdicts
    assert out["sleeves"]["premium_vrp"]["total_net_pnl"] == 40.0
    assert out["sleeves"]["premium_earnings"]["total_net_pnl"] == 55.0


def test_execution_cost_is_a_diagnostic_not_double_subtracted(monkeypatch):
    """Measured slippage (ExecutionLog) is surfaced BESIDE the edge, mapped to court sleeves — but the
    realized P&L is already fill-net, so it must NOT be subtracted again. Instrumented-but-empty,
    measured, and not-instrumented sleeves each get an honest label."""
    import app.services.execution_log_engine as el_mod
    monkeypatch.setattr(el_mod, "ExecutionLogEngine",
                        lambda: type("L", (), {"realized": lambda self: {"by_strategy": {
                            "trend": {"avg_slippage_bps": 0.8, "fill_rate_pct": 100.0, "realized_slippage_usd": 0.3}}}})())
    # no closed trades -> sleeves empty, but execution_cost still reports for every court sleeve
    monkeypatch.setattr(E, "_closed_trades", lambda self: ([], 0))
    out = E().realized_edge()
    ec = out["execution_cost"]
    assert ec["trend"]["source"] == "measured" and ec["trend"]["avg_slippage_bps"] == 0.8
    assert ec["carry"]["source"] == "instrumented — no orders logged yet"      # instrumented, no data
    assert ec["premium_vrp"]["source"] == "instrumented — no orders logged yet"  # condors now instrumented
    assert ec["momentum"]["source"].startswith("not instrumented")             # momentum still isn't
    # realized_pnl is untouched: a winning trade's net is not reduced by slippage here
    monkeypatch.setattr(E, "_closed_trades", lambda self: (_trades(1, 10.0, sleeve="trend"), 0))
    out2 = E().realized_edge()
    assert out2["sleeves"]["trend"]["total_net_pnl"] == 10.0                    # NOT 10 - slippage


def test_t_crit_is_small_sample_aware():
    # flat normal is 1.96; the small-sample t critical value is wider for small N, ~1.96 for large N
    assert round(E._t_crit(20), 2) >= 2.05          # df=19 -> ~2.09
    assert E._t_crit(20) > E._t_crit(200)           # monotone: fewer trades -> wider
    assert abs(E._t_crit(2000) - 1.96) < 0.02       # converges to the normal for large N


def test_thin_lucky_sample_not_proven_under_small_sample_t(monkeypatch):
    """A 20-trade sample with t_stat ~1.98 clears the FLAT 1.96 CI but NOT the small-sample-t CI (df=19
    ~2.09) — so the harder gate correctly withholds PROVEN where the naive normal would have granted it."""
    # net=[6.4,-2.4]*10 on risk 100 -> mean ROR 2% (above the floor), t_stat ~1.98
    trades = [{"sleeve": "premium_vrp", "gross": v, "net": v, "risk": 100.0, "closed_at": "x",
               "basis": "fills"} for v in ([6.4, -2.4] * 10)]
    monkeypatch.setattr(E, "_closed_trades", lambda self: (trades, 0))
    stat = E().realized_edge()["sleeves"]["premium_vrp"]
    assert 1.96 < stat["t_stat"] < E._t_crit(20)     # in the band the flat-z would have called significant
    assert stat["ci95_return_on_risk_pct"][0] < 0    # t-CI lower bound dips below 0
    assert "UNPROVEN" in stat["verdict"]             # NOT proven — the hardening did its job


def test_significant_but_trivial_edge_is_not_proven(monkeypatch):
    """A tight, clearly-significant edge that is below the action floor must not fire PROVEN (which would
    move capital) — it's flagged UNPROVEN 'below the action floor' instead."""
    # net alternating 0.25/0.35 on risk 100 -> mean ROR 0.3% (< 0.5% floor), tiny variance -> lo > 0
    trades = [{"sleeve": "premium_vrp", "gross": v, "net": v, "risk": 100.0, "closed_at": "x",
               "basis": "fills"} for v in ([0.25, 0.35] * 12)]
    monkeypatch.setattr(E, "_closed_trades", lambda self: (trades, 0))
    stat = E().realized_edge()["sleeves"]["premium_vrp"]
    assert stat["ci95_return_on_risk_pct"][0] > 0    # statistically positive
    assert "UNPROVEN" in stat["verdict"] and "action floor" in stat["verdict"]


def test_instrument_aware_risk_basis(tmp_path, monkeypatch):
    """Return-on-risk divides by comparable INTENDED MAX LOSS per instrument: condor = defined max_loss,
    equity = a stop-loss proxy (% of notional), NOT raw notional — so momentum's ROR is comparable."""
    vrp = tmp_path / "vrp.jsonl"
    eq = tmp_path / "eq.jsonl"
    vrp.write_text(json.dumps({"status": "CLOSED", "close_reason": "PROFIT_TAKE_50PCT", "realized_pnl": 40.0,
                               "max_loss_total": 300.0, "realized_pnl_basis": "fills"}) + "\n")
    eq.write_text(json.dumps({"status": "CLOSED", "close_reason": "TP1 hit", "realized_pnl": 60.0,
                              "asset_type": "EQUITY", "entry_price": 100.0, "quantity": 10, "symbol": "GLW"}) + "\n")
    monkeypatch.setattr(E, "VRP_LEDGER", vrp)
    monkeypatch.setattr(E, "EQ_LEDGER", eq)
    monkeypatch.setattr(E, "OPT_LEDGER", tmp_path / "none.jsonl")
    trades, _ = E()._closed_trades()

    con = next(t for t in trades if t["sleeve"] == "premium_vrp")
    assert con["risk"] == 300.0 and con["risk_kind"] == "defined_max_loss"
    eqt = next(t for t in trades if t["sleeve"] == "momentum")
    # equity notional = 100*10 = 1000; risk = 12% stop proxy = 120 (NOT the raw 1000 notional)
    assert eqt["risk"] == 120.0 and eqt["risk_kind"] == "stop_proxy_12pct"
    # so momentum ROR = 60/120 = 50% (comparable to a condor's P&L/max-loss), not 60/1000 = 6% on notional
    out = E().realized_edge()
    assert out["sleeves"]["momentum"]["risk_basis"] == "stop_proxy_12pct"
    assert out["sleeves"]["premium_vrp"]["risk_basis"] == "defined_max_loss"


def test_recorded_entry_stop_gives_exact_equity_risk(tmp_path, monkeypatch):
    """When the momentum open stamped entry_stop, the court measures return on the ACTUAL doctrine stop
    distance ('stop_atr_doctrine'), not the 12% proxy; a row without it falls back to the proxy."""
    eq = tmp_path / "eq.jsonl"
    eq.write_text("\n".join(json.dumps(r) for r in [
        # entry 100, doctrine initial_stop 90 -> risk/share 10 * 8 shares = 80 (EXACT)
        {"status": "CLOSED", "close_reason": "TP1 hit", "realized_pnl": 24.0, "asset_type": "EQUITY",
         "entry_price": 100.0, "quantity": 8, "entry_stop": 90.0, "symbol": "GLW"},
        # no entry_stop -> 12% proxy of notional (50*4=200 -> 24)
        {"status": "CLOSED", "close_reason": "TP1 hit", "realized_pnl": 5.0, "asset_type": "EQUITY",
         "entry_price": 50.0, "quantity": 4, "symbol": "ALTO"}]) + "\n")
    monkeypatch.setattr(E, "VRP_LEDGER", tmp_path / "novrp.jsonl")
    monkeypatch.setattr(E, "EQ_LEDGER", eq)
    monkeypatch.setattr(E, "OPT_LEDGER", tmp_path / "noopt.jsonl")
    trades, _ = E()._closed_trades()
    exact = next(t for t in trades if t["risk_kind"] == "stop_atr_doctrine")
    assert exact["risk"] == 80.0                       # |100-90| * 8
    proxy = next(t for t in trades if t["risk_kind"].startswith("stop_proxy"))
    assert proxy["risk"] == 24.0                       # 0.12 * (50*4)


def test_open_trade_stores_entry_atr_and_stop(tmp_path, monkeypatch):
    from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
    led = PaperTradeLedgerEngine()
    led.ledger_file = tmp_path / "led.jsonl"
    led.open_trade(symbol="GLW", side="BUY", quantity=5, entry_price=100.0,
                   trade_intent="MOMENTUM_REVERSAL", entry_atr=4.0, entry_stop=90.0)
    row = json.loads((tmp_path / "led.jsonl").read_text().splitlines()[0])
    assert row["entry_atr"] == 4.0 and row["entry_stop"] == 90.0
