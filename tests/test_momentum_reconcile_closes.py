"""Equity-exit close reconciler (momentum) — the equity mirror of VRP reconcile_closes. Momentum books
realized at the decision QUOTE and marks CLOSED on ACCEPTANCE; this pass upgrades realized to the ACTUAL
exit fills, and REVERTS a CLOSED row the broker still fully holds (the close never filled). Reverts only
the clean fantasy-flat case, only on a readable positions read, never a forced/admin flatten."""

import json

from app.services.momentum_exit_manager_engine import MomentumExitManagerEngine as E
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine


class _Booking:
    def __init__(self, positions, orders, raise_pos=False):
        self._p, self._o, self._raise = positions, orders, raise_pos

    def positions(self):
        if self._raise:
            raise RuntimeError("positions API down")
        return {"response_json": {"Positions": self._p}}

    def orders(self):
        return {"response_json": {"Orders": self._o}}


class _SimExec:
    def __init__(self, positions, orders, raise_pos=False):
        self.booking = _Booking(positions, orders, raise_pos)


def _closed(**over):
    t = {"symbol": "GLW", "status": "CLOSED", "side": "BUY", "trade_intent": "MOMENTUM_REVERSAL",
         "original_quantity": 6.0, "quantity": 6, "entry_price": 156.01, "realized_pnl": 20.0,
         "exit_reason": "STOP", "sim_exit_events": [{"order_id": "O1", "shares": 6}]}
    t.update(over)
    return t


def _pos(sym="GLW", qty="6", long=True):
    return {"Symbol": sym, "Quantity": qty, "LongShort": "Long" if long else "Short"}


def _order(oid="O1", price="160.0", qty="6", status="Filled"):
    return {"OrderID": oid, "StatusDescription": status,
            "Legs": [{"ExecutionPrice": price, "ExecQuantity": qty}]}


def _run(tmp_path, monkeypatch, trades, positions, orders, dry_run=False, raise_pos=False):
    eng = E()
    eng.ledger_file = tmp_path / "led.jsonl"
    monkeypatch.setattr(PaperTradeLedgerEngine, "_read_all", lambda self: [dict(t) for t in trades])
    monkeypatch.setattr(E, "_sim_exec", lambda self: _SimExec(positions, orders, raise_pos))
    res = eng.reconcile_closes(dry_run=dry_run)
    rows = []
    if (tmp_path / "led.jsonl").exists():
        rows = [json.loads(l) for l in (tmp_path / "led.jsonl").read_text().splitlines() if l.strip()]
    return res, rows


def test_realized_upgraded_to_actual_fills(tmp_path, monkeypatch):
    # flat at broker, exit order fully filled at 160 -> realized (160-156.01)*6 = 23.94, basis 'fills'
    res, rows = _run(tmp_path, monkeypatch, [_closed()], positions=[], orders=[_order()])
    assert res["reconciled"] == 1 and res["reverted"] == 0
    r = rows[0]
    assert r["status"] == "CLOSED" and r["realized_pnl_basis"] == "fills"
    assert r["realized_pnl"] == 23.94 and r["close_verified_flat"] is True and r["exit_reconciled"] is True


def test_short_side_realized_sign(tmp_path, monkeypatch):
    # SHORT: entry 50, cover fill 45 -> realized (cost-proceeds) = (500-450) = 50
    t = _closed(side="SELL", original_quantity=10.0, quantity=10, entry_price=50.0,
                sim_exit_events=[{"order_id": "O1", "shares": 10}])
    res, rows = _run(tmp_path, monkeypatch, [t], positions=[], orders=[_order(price="45.0", qty="10")])
    assert rows[0]["realized_pnl"] == 50.0 and rows[0]["realized_pnl_basis"] == "fills"


def test_fully_held_is_reverted_to_open(tmp_path, monkeypatch):
    # broker still holds all 6 shares -> the whole close was fantasy -> revert to OPEN, reset realized
    res, rows = _run(tmp_path, monkeypatch, [_closed()], positions=[_pos(qty="6")], orders=[])
    assert res["reverted"] == 1 and res["reconciled"] == 0
    r = rows[0]
    assert r["status"] == "OPEN" and r["quantity"] == 6.0 and r["realized_pnl"] == 0.0
    assert r["manager_status"] == "MOMENTUM_CLOSE_REVERTED_STILL_HELD"
    assert r["doctrine_state"] == {} and "exit_price" not in r and "exit_reconciled" not in r


def test_partial_held_is_flagged_not_mutated(tmp_path, monkeypatch):
    # broker still holds 3 of 6 -> ambiguous -> flag CRITICAL, leave realized as booked, keep surfacing
    res, rows = _run(tmp_path, monkeypatch, [_closed()], positions=[_pos(qty="3")], orders=[])
    assert res["flagged"] == 1 and res["reverted"] == 0 and res["reconciled"] == 0
    r = rows[0]
    assert r["status"] == "CLOSED" and r["close_verified_flat"] is False
    assert r["manager_status"] == "MOMENTUM_CLOSE_PARTIALLY_HELD"
    assert r["realized_pnl"] == 20.0 and "exit_reconciled" not in r    # keeps surfacing until resolved


def test_collision_guard_no_revert_when_reentry_open(tmp_path, monkeypatch):
    # a live re-entry holds GLW -> the held shares are explained, NOT a failed close
    reentry = _closed(status="OPEN")
    res, rows = _run(tmp_path, monkeypatch, [_closed(), reentry], positions=[_pos(qty="6")], orders=[])
    assert res["reverted"] == 0
    closed = [r for r in rows if r.get("exit_reason") == "STOP" and r["status"] == "CLOSED"]
    assert closed and closed[0]["realized_pnl_basis"] == "quote_estimate"   # fell to branch B, tagged honest


def test_forced_close_is_never_reverted(tmp_path, monkeypatch):
    # a clean-slate flatten is intentional — even if the broker still shows it, never resurrect it
    t = _closed(exit_reason="CLEAN_SLATE_FLATTEN", sim_exit_events=[])
    res, rows = _run(tmp_path, monkeypatch, [t], positions=[_pos(qty="6")], orders=[])
    assert res["reverted"] == 0 and rows[0]["status"] == "CLOSED"


def test_unreadable_positions_no_revert_no_verified_flat(tmp_path, monkeypatch):
    # a swallowed positions read is UNKNOWN, not flat -> no revert, and don't claim close_verified_flat
    t = _closed(sim_exit_events=[])
    res, rows = _run(tmp_path, monkeypatch, [t], positions=[], orders=[], raise_pos=True)
    assert res["reverted"] == 0
    r = rows[0]
    assert r["status"] == "CLOSED" and r["realized_pnl_basis"] == "quote_estimate"
    assert "close_verified_flat" not in r


def test_unfilled_exit_order_tagged_quote_estimate(tmp_path, monkeypatch):
    # flat, but the exit order isn't Filled in the book -> can't upgrade -> honest 'quote_estimate' tag
    res, rows = _run(tmp_path, monkeypatch, [_closed()], positions=[], orders=[_order(status="Received")])
    r = rows[0]
    assert r["realized_pnl"] == 20.0 and r["realized_pnl_basis"] == "quote_estimate"
    assert r["exit_reconciled"] is True and r["close_verified_flat"] is True    # broker flat, just no fill detail


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    res, rows = _run(tmp_path, monkeypatch, [_closed()], positions=[_pos(qty="6")], orders=[], dry_run=True)
    assert res["status"] == "MOMENTUM_CLOSES_RECONCILE_DRYRUN"
    assert rows == []    # nothing written to disk


def test_already_reconciled_row_is_skipped(tmp_path, monkeypatch):
    t = _closed(exit_reconciled=True, realized_pnl_basis="fills")
    res, rows = _run(tmp_path, monkeypatch, [t], positions=[], orders=[_order()])
    assert res["reconciled"] == 0 and res["reverted"] == 0
