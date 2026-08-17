"""Sleeve trade ledger makes direct-to-broker ETF sleeves visible to the edge court.

Broker-confirmed FIFO: only a CONFIRMED change in broker-held qty opens/closes a lot (an unfilled order
records nothing). The court then ingests the CLOSE rows, attributed by the explicit `sleeve` tag.
"""

import json

from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine as L
from app.services.edge_persistence_engine import EdgePersistenceEngine


def _engine(monkeypatch, tmp_path):
    monkeypatch.setattr(L, "LEDGER", tmp_path / "sleeve_trade_ledger.jsonl")
    return L()


def test_buy_opens_lot(monkeypatch, tmp_path):
    e = _engine(monkeypatch, tmp_path)
    r = e.reconcile("low_vol", "USMV", broker_qty=3, price=100.0)
    assert r["status"] == "SLEEVE_LEDGER_OPENED" and r["qty"] == 3
    assert e.held_qty("low_vol", "USMV") == 3


def test_unfilled_is_noop(monkeypatch, tmp_path):
    e = _engine(monkeypatch, tmp_path)
    e.reconcile("low_vol", "USMV", 3, 100.0)
    r = e.reconcile("low_vol", "USMV", 3, 101.0)          # broker qty unchanged → nothing filled
    assert r["status"] == "SLEEVE_LEDGER_NOOP"
    # no phantom close/lot added
    rows = [json.loads(x) for x in (tmp_path / "sleeve_trade_ledger.jsonl").read_text().splitlines()]
    assert sum(1 for x in rows if x["kind"] == "lot") == 1 and not any(x["kind"] == "close" for x in rows)


def test_sell_closes_fifo_with_realized(monkeypatch, tmp_path):
    e = _engine(monkeypatch, tmp_path)
    e.reconcile("low_vol", "USMV", 3, 100.0)              # open 3 @ 100
    r = e.reconcile("low_vol", "USMV", 1, 110.0)          # broker now 1 → sold 2 @ 110
    assert r["status"] == "SLEEVE_LEDGER_CLOSED"
    assert r["realized_total"] == 20.0                    # (110-100)*2
    assert e.held_qty("low_vol", "USMV") == 1             # 1 share remains open


def test_empty_read_does_not_fabricate_mass_close(monkeypatch, tmp_path):
    """A degraded positions read returns held=0 for the whole basket. With open lots recorded, that must
    be treated as an empty read and SKIPPED — never a fabricated mass close (the phantom bug class)."""
    e = _engine(monkeypatch, tmp_path)
    e.reconcile("low_vol", "USMV", 3, 100.0)
    e.reconcile("low_vol", "SPLV", 3, 76.0)
    # broker read comes back all-zero across the basket while we hold lots -> skip
    legs = [{"symbol": "USMV", "held": 0, "last": 100.0}, {"symbol": "SPLV", "held": 0, "last": 76.0}]
    r = e.reconcile_plan("low_vol", legs)
    assert r["status"] == "SLEEVE_LEDGER_SKIP_EMPTY_READ"
    assert e.held_qty("low_vol", "USMV") == 3 and e.held_qty("low_vol", "SPLV") == 3   # untouched


def test_genuine_single_name_sell_still_reconciles(monkeypatch, tmp_path):
    """A real single-name exit (other names still held) is NOT the empty-read case and must reconcile."""
    e = _engine(monkeypatch, tmp_path)
    e.reconcile("low_vol", "USMV", 3, 100.0)
    e.reconcile("low_vol", "SPLV", 3, 76.0)
    legs = [{"symbol": "USMV", "held": 0, "last": 105.0}, {"symbol": "SPLV", "held": 3, "last": 76.0}]
    r = e.reconcile_plan("low_vol", legs)          # USMV genuinely exited, SPLV held → not empty-read
    assert r["status"] == "SLEEVE_LEDGER_RECONCILED"
    assert e.held_qty("low_vol", "USMV") == 0 and e.held_qty("low_vol", "SPLV") == 3


def test_court_ingests_sleeve_closes_attributed(monkeypatch, tmp_path):
    # isolate ALL court ledgers to empty tmp files except the sleeve ledger we seed
    for attr in ("VRP_LEDGER", "OPT_LEDGER", "EQ_LEDGER"):
        monkeypatch.setattr(EdgePersistenceEngine, attr, tmp_path / f"{attr}.jsonl")
    monkeypatch.setattr(EdgePersistenceEngine, "SLEEVE_LEDGER", tmp_path / "sleeve.jsonl")
    (tmp_path / "sleeve.jsonl").write_text(
        json.dumps({"kind": "close", "sleeve": "low_vol", "symbol": "USMV", "quantity": 2,
                    "entry_price": 100.0, "exit_price": 110.0, "realized_pnl": 20.0,
                    "closed_at": "2026-08-05T14:00:00", "close_reason": "REBALANCE",
                    "status": "CLOSED", "realized_pnl_basis": "quote_estimate"}) + "\n")
    trades, excluded = EdgePersistenceEngine()._closed_trades()
    lv = [t for t in trades if t["sleeve"] == "low_vol"]
    assert len(lv) == 1 and lv[0]["net"] == 20.0 and lv[0]["risk"] > 0
    # hybrid read-map: a sleeve-ledger close is broker-confirmed-qty by construction, so a legacy
    # 'quote_estimate' tag reads back as the confirmation FLOOR 'mark_at_confirm', not a loose estimate.
    assert lv[0]["basis"] == "mark_at_confirm"


def test_reconcile_close_tags_mark_at_confirm(monkeypatch, tmp_path):
    # a fresh close from reconcile (broker qty dropped) is tagged mark_at_confirm, not quote_estimate
    e = _engine(monkeypatch, tmp_path)
    e.reconcile("low_vol", "USMV", 3, 100.0)              # open 3 @ 100
    e.reconcile("low_vol", "USMV", 1, 110.0)              # broker now 1 → sold 2 @ 110
    rows = [json.loads(x) for x in (tmp_path / "sleeve_trade_ledger.jsonl").read_text().splitlines()]
    closes = [r for r in rows if r.get("kind") == "close"]
    assert closes and all(r["realized_pnl_basis"] == "mark_at_confirm" for r in closes)


def test_upgrade_promotes_mark_at_confirm_to_real_fill(monkeypatch, tmp_path):
    # when a real executed SELL fill IS captured, the floor upgrades to 'fills' at the executed price
    e = _engine(monkeypatch, tmp_path)
    e.reconcile("low_vol", "USMV", 3, 100.0)
    e.reconcile("low_vol", "USMV", 1, 110.0)             # close 2 @ mark 110 (mark_at_confirm)
    close = [r for r in [json.loads(x) for x in (tmp_path / "sleeve_trade_ledger.jsonl").read_text().splitlines()]
             if r.get("kind") == "close"][0]
    csecs = L()._ts_secs(close["closed_at"])
    import app.services.execution_log_engine as elmod

    class _XE:
        def _intents(self):
            return [{"strategy": "low_vol", "symbol": "USMV", "action": "SELL", "qty": 2,
                     "order_id": "OID1", "ts": close["closed_at"]}]
        def _broker_fills(self):
            return {"OID1": 109.5}                        # the ACTUAL executed price

    monkeypatch.setattr(elmod, "ExecutionLogEngine", _XE)
    r = e.upgrade_close_fills()
    assert r["upgraded"] == 1
    up = [x for x in [json.loads(y) for y in (tmp_path / "sleeve_trade_ledger.jsonl").read_text().splitlines()]
          if x.get("kind") == "close"][0]
    assert up["realized_pnl_basis"] == "fills" and up["exit_price"] == 109.5


def test_court_excludes_forced_sleeve_close(monkeypatch, tmp_path):
    for attr in ("VRP_LEDGER", "OPT_LEDGER", "EQ_LEDGER"):
        monkeypatch.setattr(EdgePersistenceEngine, attr, tmp_path / f"{attr}.jsonl")
    monkeypatch.setattr(EdgePersistenceEngine, "SLEEVE_LEDGER", tmp_path / "sleeve.jsonl")
    (tmp_path / "sleeve.jsonl").write_text(
        json.dumps({"kind": "close", "sleeve": "trend", "symbol": "QQQM", "quantity": 1,
                    "entry_price": 100.0, "exit_price": 90.0, "realized_pnl": -10.0,
                    "closed_at": "2026-08-05T14:00:00", "close_reason": "CLEAN_SLATE_FLATTEN",
                    "status": "CLOSED"}) + "\n")
    trades, excluded = EdgePersistenceEngine()._closed_trades()
    assert not any(t["sleeve"] == "trend" for t in trades) and excluded >= 1
