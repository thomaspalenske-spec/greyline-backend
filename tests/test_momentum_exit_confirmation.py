"""Root A: a momentum exit must bank realized P&L / mark CLOSED only when the broker CONFIRMS the fill.

No real orders — the SIM mirror and ledger I/O are fully mocked.
"""

import app.services.momentum_exit_manager_engine as mem
from app.services.momentum_exit_manager_engine import MomentumExitManagerEngine


def _run(monkeypatch, mirror_result):
    eng = MomentumExitManagerEngine()
    trade = {"symbol": "AAPL", "status": "OPEN", "trade_intent": eng.TRADE_INTENT, "side": "BUY",
             "realized_pnl": 0.0, "quantity": 10, "original_quantity": 10,
             "doctrine_state": {"remaining_quantity": 10}}
    close_state = {"remaining_quantity": 0}
    close_action = [{"type": "CLOSE", "qty": 10, "price": 150.0, "reason": "STOP", "realized": 50.0}]

    monkeypatch.setattr(mem.PaperTradeLedgerEngine, "_read_all", lambda self: [trade])
    monkeypatch.setattr(mem.TradeStationQuoteLiveEngine, "get_quote",
                        lambda self, sym: {"response_json": {"Quotes": [{"Last": "150"}]}})
    monkeypatch.setattr(eng, "_ensure_doctrine", lambda t: True)
    monkeypatch.setattr(eng, "decide", lambda t, p, n: (close_action, close_state))
    monkeypatch.setattr(eng, "_mirror_exits_to_sim", lambda t, a, s: mirror_result)
    monkeypatch.setattr(eng, "_alert_unconfirmed_exit", lambda t, m: None)
    monkeypatch.setattr(mem, "atomic_write_text", lambda path, txt: None)

    res = eng.manage_open_positions()
    return trade, res


def test_unconfirmed_exit_stays_open_and_banks_nothing(monkeypatch):
    trade, res = _run(monkeypatch, {"attempted": True, "ok": False, "reason": "STOP → SIM_BOOKED"})
    assert trade["status"] == "OPEN"                       # NOT closed on intent
    assert trade["realized_pnl"] == 0.0                    # no fantasy realized banked
    assert trade["manager_status"] == "MOMENTUM_EXIT_UNCONFIRMED"
    assert res["closed"] == 0


def test_confirmed_exit_closes_and_banks_realized(monkeypatch):
    trade, res = _run(monkeypatch, {"attempted": True, "ok": True, "reason": None})
    assert trade["status"] == "CLOSED"
    assert trade["realized_pnl"] == 50.0                   # banked only after broker confirmation
    assert "manager_status" not in trade
    assert res["closed"] == 1


def test_no_sim_counterpart_falls_back_to_internal_doctrine(monkeypatch):
    # Nothing to confirm against (SIM off / sub-share) → attempted=False → commit as before.
    trade, res = _run(monkeypatch, {"attempted": False, "ok": True, "reason": "no SIM counterpart"})
    assert trade["status"] == "CLOSED" and res["closed"] == 1
