"""Options-exit close reconciler — the long-option mirror of VRP/momentum reconcile_closes, and the last
of the class. The options manager marks CLOSED whenever _book_close reports ok, which INCLUDES
NO_SIM_OPTION_POSITION (a status a degraded positions read ALSO returns), and books NO realized_pnl. This
pass computes realized from the actual SELLTOCLOSE fills and reverts a CLOSED option the broker still holds."""

import json

from app.services.options_position_manager_engine import OptionsPositionManagerEngine as O


class _Booking:
    def __init__(self, positions, orders, raise_pos=False):
        self._p, self._o, self._raise = positions, orders, raise_pos

    def positions(self):
        if self._raise:
            raise RuntimeError("positions API down")
        return {"response_json": {"Positions": self._p}}

    def orders(self):
        return {"response_json": {"Orders": self._o}}


class _Sim:
    def __init__(self, positions, orders, raise_pos=False):
        self.booking = _Booking(positions, orders, raise_pos)


def _closed(**over):
    t = {"option_symbol": "AAPL 260116C200", "underlying": "AAPL", "status": "CLOSED",
         "option_type": "Call", "contracts": 0, "original_contracts": 4, "entry_price": 2.00,
         "underlying_entry_price": 190.0, "exit_reason": "OPTIONS_DOCTRINE_STOP",
         "exit_events": [{"reason": "STOP", "contracts": 4, "sim": "SIM_OPTION_CLOSE_BOOKED",
                          "order_id": "OX1"}]}
    t.update(over)
    return t


def _opt_pos(sym="AAPL 260116C200", qty="4"):
    return {"Symbol": sym, "Quantity": qty, "AssetType": "STOCKOPTION", "LongShort": "Long"}


def _order(oid="OX1", price="3.50", qty="4", status="Filled"):
    return {"OrderID": oid, "StatusDescription": status,
            "Legs": [{"ExecutionPrice": price, "ExecQuantity": qty}]}


def _run(tmp_path, monkeypatch, trades, positions, orders, dry_run=False, raise_pos=False):
    led = tmp_path / "options.jsonl"
    led.write_text("\n".join(json.dumps(t) for t in trades) + ("\n" if trades else ""))
    eng = O()
    eng.ledger_file = led
    monkeypatch.setattr(O, "_sim", lambda self: _Sim(positions, orders, raise_pos))
    res = eng.reconcile_closes(dry_run=dry_run)
    rows = [json.loads(l) for l in led.read_text().splitlines() if l.strip()]
    return res, rows


def test_realized_computed_from_actual_close_fills(tmp_path, monkeypatch):
    # flat; exit fully filled at 3.50 vs entry 2.00 on 4 contracts -> (3.50-2.00)*4*100 = 600
    res, rows = _run(tmp_path, monkeypatch, [_closed()], positions=[], orders=[_order()])
    assert res["reconciled"] == 1 and res["reverted"] == 0
    r = rows[0]
    assert r["status"] == "CLOSED" and r["realized_pnl_basis"] == "fills"
    assert r["realized_pnl"] == 600.0 and r["original_quantity"] == 4 and r["exit_reconciled"] is True


def test_still_held_phantom_close_is_reverted(tmp_path, monkeypatch):
    # broker still holds all 4 contracts -> the 'close' was a degraded-read phantom -> revert to OPEN
    res, rows = _run(tmp_path, monkeypatch, [_closed()], positions=[_opt_pos(qty="4")], orders=[])
    assert res["reverted"] == 1 and res["reconciled"] == 0
    r = rows[0]
    assert r["status"] == "OPEN" and r["contracts"] == 4
    assert r["manager_status"] == "OPTION_CLOSE_REVERTED_STILL_HELD"
    assert r["doctrine_state_u"]["remaining_contracts"] == 4
    assert "realized_pnl" not in r and "exit_reason" not in r


def test_partial_held_is_flagged(tmp_path, monkeypatch):
    res, rows = _run(tmp_path, monkeypatch, [_closed()], positions=[_opt_pos(qty="2")], orders=[])
    assert res["flagged"] == 1 and res["reverted"] == 0
    r = rows[0]
    assert r["status"] == "CLOSED" and r["close_verified_flat"] is False
    assert r["manager_status"] == "OPTION_CLOSE_PARTIALLY_HELD" and "exit_reconciled" not in r


def test_unreconciled_when_fills_unreadable_never_fabricates(tmp_path, monkeypatch):
    # flat, but the exit order isn't Filled -> cannot price -> basis 'unreconciled', NO realized booked
    res, rows = _run(tmp_path, monkeypatch, [_closed()], positions=[], orders=[_order(status="Received")])
    r = rows[0]
    assert "realized_pnl" not in r and r["realized_pnl_basis"] == "unreconciled"
    assert r["exit_reconciled"] is True and r["close_verified_flat"] is True


def test_unreadable_positions_no_revert(tmp_path, monkeypatch):
    # degraded positions read is UNKNOWN, not flat -> no revert; still tags honestly, no verified_flat
    t = _closed(exit_events=[{"reason": "STOP", "contracts": 0, "sim": "NO_SIM_OPTION_POSITION",
                              "order_id": None}])
    res, rows = _run(tmp_path, monkeypatch, [t], positions=[], orders=[], raise_pos=True)
    assert res["reverted"] == 0
    r = rows[0]
    assert r["status"] == "CLOSED" and r["realized_pnl_basis"] == "unreconciled"
    assert "close_verified_flat" not in r


def test_collision_guard_no_revert_on_reentry(tmp_path, monkeypatch):
    reentry = _closed(status="OPEN")
    res, rows = _run(tmp_path, monkeypatch, [_closed(exit_events=[]), reentry],
                     positions=[_opt_pos(qty="4")], orders=[])
    assert res["reverted"] == 0
    closed = [r for r in rows if r["status"] == "CLOSED"]
    assert closed and closed[0]["realized_pnl_basis"] == "unreconciled"


def test_forced_close_not_reverted(tmp_path, monkeypatch):
    t = _closed(exit_reason="CLEAN_SLATE_FLATTEN", exit_events=[])
    res, rows = _run(tmp_path, monkeypatch, [t], positions=[_opt_pos(qty="4")], orders=[])
    assert res["reverted"] == 0 and rows[0]["status"] == "CLOSED"


def test_partial_fills_short_of_original_not_upgraded(tmp_path, monkeypatch):
    # only 2 of 4 contracts show a fill -> acc_qty != orig -> not fills, honest 'unreconciled'
    t = _closed(exit_events=[{"reason": "TP1", "contracts": 2, "sim": "SIM_OPTION_CLOSE_BOOKED",
                              "order_id": "OX1"}])
    res, rows = _run(tmp_path, monkeypatch, [t], positions=[], orders=[_order(qty="2")])
    r = rows[0]
    assert "realized_pnl" not in r and r["realized_pnl_basis"] == "unreconciled"


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    led = tmp_path / "options.jsonl"
    trades = [_closed()]
    led.write_text("\n".join(json.dumps(t) for t in trades) + "\n")
    before = led.read_text()
    eng = O()
    eng.ledger_file = led
    monkeypatch.setattr(O, "_sim", lambda self: _Sim([_opt_pos()], []))
    res = eng.reconcile_closes(dry_run=True)
    assert res["status"] == "OPTIONS_CLOSES_RECONCILE_DRYRUN"
    assert led.read_text() == before
