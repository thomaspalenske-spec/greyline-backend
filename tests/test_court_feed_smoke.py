"""COURT-FEED SMOKE HARNESS — proves a closed trade actually flows all the way into the edge court, for
every instrument, through the REAL reconcilers and the REAL EdgePersistenceEngine (no mocked court math):

    estimate-priced CLOSED row  →  reconcile_closes (basis → 'fills')  →  realized_edge() counts it

This is the guarantee that when Monday's real fills land, they don't silently stop at 'reconciled' but
show up in the court with the right sleeve, risk basis, and return-on-risk. One test per instrument
(condor / momentum equity / long option) + a combined test that all three land together.
"""

import json

import app.services.execution_log_engine as el_mod
from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V
from app.services.momentum_exit_manager_engine import MomentumExitManagerEngine as MOM
from app.services.options_position_manager_engine import OptionsPositionManagerEngine as OPT
from app.services.edge_persistence_engine import EdgePersistenceEngine
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine


# ----------------------------------------------------------------------- broker mocks (real fills)
class _OrdersOnly:
    def __init__(self, orders):
        self._o = orders

    def orders(self):
        return {"response_json": {"Orders": self._o}}


class _SimBooking:
    def __init__(self, positions, orders):
        self._p, self._o = positions, orders

    def positions(self):
        return {"response_json": {"Positions": self._p}}

    def orders(self):
        return {"response_json": {"Orders": self._o}}


class _Sim:
    def __init__(self, positions, orders):
        self.booking = _SimBooking(positions, orders)


class _AtomicFilled:
    """Atomic condor close, fully filled: net buy-back 0.50+0.50, wing-sell 0.35+0.35 → debit 0.30."""
    FILLS = {"X 261218C110": ("Buy", 0.50), "X 261218P90": ("Buy", 0.50),
             "X 261218C115": ("Sell", 0.35), "X 261218P85": ("Sell", 0.35)}

    def orders(self):
        return {"response_json": {"Orders": [{
            "OrderID": "ATOM-1", "StatusDescription": "Filled", "FilledPrice": "0.30",
            "Legs": [{"Symbol": s, "BuyOrSell": bs, "OpenOrClose": "Close", "ExecutionPrice": px,
                      "ExecQuantity": "1", "QuantityOrdered": "1"}
                     for s, (bs, px) in self.FILLS.items()]}]}}


def _point_court(monkeypatch, tmp_path, vrp=None, eq=None, opt=None):
    monkeypatch.setattr(EdgePersistenceEngine, "VRP_LEDGER", vrp or tmp_path / "none_vrp.jsonl")
    monkeypatch.setattr(EdgePersistenceEngine, "EQ_LEDGER", eq or tmp_path / "none_eq.jsonl")
    monkeypatch.setattr(EdgePersistenceEngine, "OPT_LEDGER", opt or tmp_path / "none_opt.jsonl")
    # keep the reconcilers' close-slippage logging off the real ExecutionLog
    monkeypatch.setattr(el_mod.ExecutionLogEngine, "LEDGER", tmp_path / "exec.jsonl")
    monkeypatch.setattr(el_mod.ExecutionLogEngine, "DIR", tmp_path)


# ============================================================================ CONDOR
def _condor_row():
    return {"symbol": "X", "quantity": 1, "status": "CLOSED", "expiration": "2026-12-18",
            "credit_per_condor": 1.0, "credit_total": 100.0, "max_loss_total": 400.0,
            "close_reason": "PROFIT_TAKE_50PCT", "closed_at": "2026-08-01T15:00:00",
            "realized_pnl": 60.0, "realized_pnl_basis": "close_order", "close_mid": 0.45,
            "legs": [{"symbol": "X 261218C110", "action": "SELLTOOPEN"},
                     {"symbol": "X 261218C115", "action": "BUYTOOPEN"},
                     {"symbol": "X 261218P90", "action": "SELLTOOPEN"},
                     {"symbol": "X 261218P85", "action": "BUYTOOPEN"}],
            "close_attempts": [{"legs": [{"symbol": s, "action": "BUYTOCLOSE", "ok": True,
                                          "order_id": "ATOM-1", "atomic": True}
                                         for s in ("X 261218C110", "X 261218C115",
                                                   "X 261218P90", "X 261218P85")]}]}


def test_condor_flows_into_court(tmp_path, monkeypatch):
    vrp = tmp_path / "vrp.jsonl"
    vrp.write_text(json.dumps(_condor_row()) + "\n")
    monkeypatch.setattr(V, "LEDGER", vrp)
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setattr(V, "_booking", lambda self: _AtomicFilled())
    monkeypatch.setattr(V, "_broker_fills", lambda self: {})       # flat: not still held
    _point_court(monkeypatch, tmp_path, vrp=vrp)

    # 1) reconcile upgrades the estimate to the actual fill
    rec = V().reconcile_closes(dry_run=False)
    row = json.loads(vrp.read_text().splitlines()[0])
    assert rec["reconciled"] == 1 and row["realized_pnl_basis"] == "fills" and row["realized_pnl"] == 70.0

    # 2) the court counts it: right sleeve, right risk basis, realized == fill P&L
    court = EdgePersistenceEngine().realized_edge()
    s = court["sleeves"]["premium_vrp"]
    assert s["trades"] == 1 and s["total_net_pnl"] == 70.0 and s["risk_basis"] == "defined_max_loss"
    assert s["mean_return_on_risk_pct"] == 17.5 and s["verdict"].startswith("ACCUMULATING (1/20")


# ============================================================================ MOMENTUM EQUITY
def _momentum_row():
    return {"symbol": "GLW", "status": "CLOSED", "side": "BUY", "trade_intent": "MOMENTUM_REVERSAL",
            "original_quantity": 6.0, "quantity": 6, "entry_price": 156.01, "entry_stop": 150.0,
            "realized_pnl": 20.0, "exit_reason": "STOP", "closed_at": "2026-08-01T15:00:00",
            "sim_exit_events": [{"order_id": "MO1", "shares": 6}]}


def test_momentum_flows_into_court(tmp_path, monkeypatch):
    eq = tmp_path / "eq.jsonl"
    eq.write_text(json.dumps(_momentum_row()) + "\n")
    monkeypatch.setattr(PaperTradeLedgerEngine, "_read_all",
                        lambda self: [json.loads(l) for l in eq.read_text().splitlines() if l.strip()])
    order = {"OrderID": "MO1", "StatusDescription": "Filled",
             "Legs": [{"ExecutionPrice": "160.0", "ExecQuantity": "6"}]}
    monkeypatch.setattr(MOM, "_sim_exec", lambda self: _Sim(positions=[], orders=[order]))
    _point_court(monkeypatch, tmp_path, eq=eq)

    eng = MOM()
    eng.ledger_file = eq
    rec = eng.reconcile_closes(dry_run=False)
    row = json.loads(eq.read_text().splitlines()[0])
    # (160-156.01)*6 = 23.94, basis fills
    assert rec["reconciled"] == 1 and row["realized_pnl_basis"] == "fills" and row["realized_pnl"] == 23.94

    court = EdgePersistenceEngine().realized_edge()
    s = court["sleeves"]["momentum"]
    assert s["trades"] == 1 and s["total_net_pnl"] == 23.94 and s["risk_basis"] == "stop_atr_doctrine"
    assert s["mean_return_on_risk_pct"] is not None and s["verdict"].startswith("ACCUMULATING (1/20")


# ============================================================================ LONG OPTION
def _option_row():
    return {"option_symbol": "AAPL 260116C200", "underlying": "AAPL", "status": "CLOSED",
            "option_type": "Call", "asset_type": "STOCKOPTION", "contracts": 0, "original_contracts": 4,
            "entry_price": 2.00, "underlying_entry_price": 190.0, "exit_reason": "OPTIONS_DOCTRINE_STOP",
            "exit_events": [{"reason": "STOP", "contracts": 4, "sim": "SIM_OPTION_CLOSE_BOOKED",
                             "order_id": "OO1"}]}


def test_option_flows_into_court(tmp_path, monkeypatch):
    opt = tmp_path / "opt.jsonl"
    opt.write_text(json.dumps(_option_row()) + "\n")
    order = {"OrderID": "OO1", "StatusDescription": "Filled",
             "Legs": [{"ExecutionPrice": "3.50", "ExecQuantity": "4"}]}
    monkeypatch.setattr(OPT, "_sim", lambda self: _Sim(positions=[], orders=[order]))
    _point_court(monkeypatch, tmp_path, opt=opt)

    eng = OPT()
    eng.ledger_file = opt
    rec = eng.reconcile_closes(dry_run=False)
    row = json.loads(opt.read_text().splitlines()[0])
    # (3.50-2.00)*4*100 = 600, basis fills, original_quantity stamped for the court
    assert rec["reconciled"] == 1 and row["realized_pnl_basis"] == "fills" and row["realized_pnl"] == 600.0
    assert row["original_quantity"] == 4

    court = EdgePersistenceEngine().realized_edge()
    s = court["sleeves"]["premium"]        # _sleeve_of buckets a long option under 'premium'
    assert s["trades"] == 1 and s["total_net_pnl"] == 600.0 and s["risk_basis"] == "premium_at_risk"
    assert s["mean_return_on_risk_pct"] == 75.0 and s["verdict"].startswith("ACCUMULATING (1/20")


# ============================================================================ ALL THREE AT ONCE
def test_all_three_sleeves_land_in_the_court_together(tmp_path, monkeypatch):
    vrp, eq, opt = tmp_path / "vrp.jsonl", tmp_path / "eq.jsonl", tmp_path / "opt.jsonl"
    vrp.write_text(json.dumps(_condor_row()) + "\n")
    eq.write_text(json.dumps(_momentum_row()) + "\n")
    opt.write_text(json.dumps(_option_row()) + "\n")

    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setattr(V, "LEDGER", vrp)
    monkeypatch.setattr(V, "_booking", lambda self: _AtomicFilled())
    monkeypatch.setattr(V, "_broker_fills", lambda self: {})
    monkeypatch.setattr(PaperTradeLedgerEngine, "_read_all",
                        lambda self: [json.loads(l) for l in eq.read_text().splitlines() if l.strip()])
    monkeypatch.setattr(MOM, "_sim_exec", lambda self: _Sim(
        positions=[], orders=[{"OrderID": "MO1", "StatusDescription": "Filled",
                               "Legs": [{"ExecutionPrice": "160.0", "ExecQuantity": "6"}]}]))
    monkeypatch.setattr(OPT, "_sim", lambda self: _Sim(
        positions=[], orders=[{"OrderID": "OO1", "StatusDescription": "Filled",
                               "Legs": [{"ExecutionPrice": "3.50", "ExecQuantity": "4"}]}]))
    _point_court(monkeypatch, tmp_path, vrp=vrp, eq=eq, opt=opt)

    V().reconcile_closes(dry_run=False)
    m = MOM(); m.ledger_file = eq; m.reconcile_closes(dry_run=False)
    o = OPT(); o.ledger_file = opt; o.reconcile_closes(dry_run=False)

    sleeves = EdgePersistenceEngine().realized_edge()["sleeves"]
    # every instrument reached the court, each fill-truthful, none excluded as forced
    assert sleeves["premium_vrp"]["trades"] == 1 and sleeves["premium_vrp"]["total_net_pnl"] == 70.0
    assert sleeves["momentum"]["trades"] == 1 and sleeves["momentum"]["total_net_pnl"] == 23.94
    assert sleeves["premium"]["trades"] == 1 and sleeves["premium"]["total_net_pnl"] == 600.0
