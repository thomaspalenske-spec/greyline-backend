"""Close-side fill reconciler: a condor is marked CLOSED on order ACCEPTANCE (estimate-priced). This pass
upgrades the estimate to the ACTUAL fill P&L once readable, and REVERTS a CLOSED row the broker still holds
(the close never filled) — a CLOSED-that-wasn't is fantasy-flat, the worst case, because risk is still live.
Reverts only on POSITIVE broker evidence, never on an empty/blipped positions read."""

import json

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def _closed_condor(**over):
    r = {"symbol": "X", "quantity": 1, "status": "CLOSED", "expiration": "2026-12-18",
         "credit_per_condor": 1.0, "credit_total": 100.0, "max_loss_total": 400.0,
         "close_reason": "PROFIT_TAKE_50PCT", "closed_at": "2026-08-01T15:00:00",
         "realized_pnl": 60.0, "realized_pnl_basis": "close_order", "close_mid": 0.45,
         "legs": [{"symbol": "X 261218C110", "action": "SELLTOOPEN"},
                  {"symbol": "X 261218C115", "action": "BUYTOOPEN"},
                  {"symbol": "X 261218P90", "action": "SELLTOOPEN"},
                  {"symbol": "X 261218P85", "action": "BUYTOOPEN"}],
         "close_attempts": [{"at": "2026-08-01T15:00:00", "reason": "PROFIT_TAKE_50PCT", "all_ok": True,
                             "legs": [{"symbol": "X 261218C110", "action": "BUYTOCLOSE", "ok": True,
                                       "order_id": "ATOM-1", "atomic": True},
                                      {"symbol": "X 261218C115", "action": "SELLTOCLOSE", "ok": True,
                                       "order_id": "ATOM-1", "atomic": True},
                                      {"symbol": "X 261218P90", "action": "BUYTOCLOSE", "ok": True,
                                       "order_id": "ATOM-1", "atomic": True},
                                      {"symbol": "X 261218P85", "action": "SELLTOCLOSE", "ok": True,
                                       "order_id": "ATOM-1", "atomic": True}]}]}
    r.update(over)
    return r


class _FilledOrders:
    """Booking whose orders() reports the atomic close FULLY filled (per-leg ExecutionPrice, exq==ordq)."""
    FILLS = {"X 261218C110": ("Buy", 0.50), "X 261218P90": ("Buy", 0.50),
             "X 261218C115": ("Sell", 0.35), "X 261218P85": ("Sell", 0.35)}   # net debit 0.30

    def orders(self):
        return {"response_json": {"Orders": [{
            "OrderID": "ATOM-1", "StatusDescription": "Filled", "FilledPrice": "0.30",
            "Legs": [{"Symbol": s, "BuyOrSell": bs, "OpenOrClose": "Close", "ExecutionPrice": px,
                      "ExecQuantity": "1", "QuantityOrdered": "1"}
                     for s, (bs, px) in self.FILLS.items()]}]}}


class _NoFillOrders:
    """Booking whose close order never filled — orders() returns nothing usable."""
    def orders(self):
        return {"response_json": {"Orders": []}}


def _setup(tmp_path, monkeypatch, rows, booking, held):
    led = tmp_path / "vrp.jsonl"
    led.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(V, "LEDGER", led)
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setattr(V, "_booking", lambda self: booking)
    monkeypatch.setattr(V, "_broker_fills", lambda self: held)
    return led


def test_estimate_close_upgraded_to_actual_fill(tmp_path, monkeypatch):
    led = _setup(tmp_path, monkeypatch, [_closed_condor()], _FilledOrders(), {})
    res = V().reconcile_closes(dry_run=False)
    row = json.loads(led.read_text().splitlines()[0])
    # actual net debit 0.30 -> realized (1.0-0.30)*100 = 70, basis upgraded from the close_order estimate
    assert res["reconciled"] == 1 and res["reverted"] == 0
    assert row["status"] == "CLOSED" and row["realized_pnl_basis"] == "fills"
    assert row["realized_pnl"] == 70.0 and row["close_reconciled"] is True


def test_closed_but_still_held_is_reverted_to_open(tmp_path, monkeypatch):
    held = {"X 261218C110": {"avg": 0.5, "long": False}}   # a short leg the broker still holds
    led = _setup(tmp_path, monkeypatch, [_closed_condor()], _NoFillOrders(), held)
    res = V().reconcile_closes(dry_run=False)
    row = json.loads(led.read_text().splitlines()[0])
    assert res["reverted"] == 1 and res["reconciled"] == 0
    assert row["status"] == "OPEN"
    assert row["manager_status"] == "VRP_CLOSE_REVERTED_STILL_HELD"
    # the fantasy realized P&L booked on acceptance is erased
    assert "realized_pnl" not in row and "realized_pnl_basis" not in row and "closed_at" not in row


def test_no_revert_when_symbol_explained_by_another_open_row(tmp_path, monkeypatch):
    # a re-opened condor reuses the same option symbol -> the held leg is explained, NOT a failed close
    open_dup = _closed_condor(symbol="X", status="OPEN")
    held = {"X 261218C110": {"avg": 0.5, "long": False}}
    led = _setup(tmp_path, monkeypatch, [_closed_condor(), open_dup], _NoFillOrders(), held)
    res = V().reconcile_closes(dry_run=False)
    assert res["reverted"] == 0
    closed = [r for r in (json.loads(l) for l in led.read_text().splitlines()) if r.get("close_reason")]
    assert closed and closed[0]["status"] == "CLOSED"    # left alone (collision guard)


def test_no_revert_on_empty_broker_read(tmp_path, monkeypatch):
    # empty positions read is UNKNOWN, not proof of a fill — never resurrect a genuinely-closed trade
    led = _setup(tmp_path, monkeypatch, [_closed_condor()], _NoFillOrders(), {})
    res = V().reconcile_closes(dry_run=False)
    row = json.loads(led.read_text().splitlines()[0])
    assert res["reverted"] == 0 and row["status"] == "CLOSED"


def test_fills_basis_row_is_left_untouched(tmp_path, monkeypatch):
    held = {"X 261218C110": {"avg": 0.5, "long": False}}   # even if held, a fills-basis close is trusted
    led = _setup(tmp_path, monkeypatch, [_closed_condor(realized_pnl_basis="fills")], _NoFillOrders(), held)
    res = V().reconcile_closes(dry_run=False)
    row = json.loads(led.read_text().splitlines()[0])
    assert res["reconciled"] == 0 and res["reverted"] == 0
    assert row["status"] == "CLOSED" and row["realized_pnl_basis"] == "fills"


def test_upgrade_logs_close_slippage_once(tmp_path, monkeypatch):
    led = _setup(tmp_path, monkeypatch, [_closed_condor()], _FilledOrders(), {})
    import app.services.execution_log_engine as el_mod
    monkeypatch.setattr(el_mod.ExecutionLogEngine, "LEDGER", tmp_path / "exec.jsonl")
    monkeypatch.setattr(el_mod.ExecutionLogEngine, "DIR", tmp_path)
    V().reconcile_closes(dry_run=False)
    recs = [json.loads(l) for l in (tmp_path / "exec.jsonl").read_text().splitlines() if l.strip()]
    pv = [x for x in recs if x.get("strategy") == "premium_vrp"]
    assert pv and pv[0]["action"] == "BUY" and pv[0]["mid"] is not None and pv[0]["fill_price"] is not None
    row = json.loads(led.read_text().splitlines()[0])
    assert row["close_slippage_logged"] is True
    # idempotent: a second pass logs nothing new
    V().reconcile_closes(dry_run=False)
    recs2 = [json.loads(l) for l in (tmp_path / "exec.jsonl").read_text().splitlines() if l.strip()]
    assert len([x for x in recs2 if x.get("strategy") == "premium_vrp"]) == len(pv)


def test_dry_run_does_not_mutate_the_ledger(tmp_path, monkeypatch):
    held = {"X 261218C110": {"avg": 0.5, "long": False}}
    led = _setup(tmp_path, monkeypatch, [_closed_condor()], _NoFillOrders(), held)
    before = led.read_text()
    res = V().reconcile_closes(dry_run=True)
    assert res["status"] == "VRP_CLOSES_RECONCILE_DRYRUN"
    assert led.read_text() == before    # dry-run reports intent, writes nothing
