"""Fill-confirmation for direct-to-broker sleeve closes + the court's estimate/confirmed honesty.

The sleeve close path prices exits at the position MARK (basis 'quote_estimate'), so the edge court used
to judge sleeves on estimated exits. These tests weld the honest behavior:
  * upgrade_close_fills() upgrades a quote_estimate close to a REAL broker fill when it can join the sell
    (via ExecutionLog order_id -> broker fill), and ABSTAINS (leaves it honest) when it cannot.
  * the court surfaces estimated vs fill-confirmed trade counts and flags an estimate-based verdict
    PROVISIONAL — so no verdict silently rests on marks.

No broker orders are placed (ExecutionLog reads are monkeypatched); conftest also blocks order calls.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine
from app.services.edge_persistence_engine import EdgePersistenceEngine


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _close_row(sleeve, symbol, qty, entry, closed_at, basis="quote_estimate"):
    return {"kind": "close", "sleeve": sleeve, "symbol": symbol, "quantity": qty,
            "entry_price": entry, "exit_price": entry, "realized_pnl": 0.0,
            "opened_at": "2026-08-08T13:00:00", "closed_at": closed_at,
            "close_reason": "REBALANCE", "status": "CLOSED", "realized_pnl_basis": basis}


def test_upgrade_close_fills_upgrades_matched_row(tmp_path, monkeypatch):
    ledger = tmp_path / "sleeve_trade_ledger.jsonl"
    closed_at = "2026-08-08T14:30:05"
    _write(ledger, [_close_row("xs_momentum", "IWM", 2, 200.0, closed_at)])
    monkeypatch.setattr(SleeveTradeLedgerEngine, "LEDGER", ledger)

    # ExecutionLog: a SELL of IWM x2 at order OID1, filled at 205.0 (in-window), placed just before the close.
    sell_ts = "2026-08-08T14:30:00"
    from app.services import execution_log_engine as xmod
    monkeypatch.setattr(xmod.ExecutionLogEngine, "_intents",
                        lambda self: [{"strategy": "xs_momentum", "symbol": "IWM", "action": "SELL",
                                       "qty": 2, "order_id": "OID1", "ts": sell_ts}])
    monkeypatch.setattr(xmod.ExecutionLogEngine, "_broker_fills", lambda self: {"OID1": 205.0})

    res = SleeveTradeLedgerEngine().upgrade_close_fills()
    assert res["upgraded"] == 1, res

    row = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()][0]
    assert row["realized_pnl_basis"] == "fills"
    assert row["exit_price"] == 205.0
    assert row["realized_pnl"] == 10.0            # (205 - 200) * 2
    assert row["fill_order_id"] == "OID1"


def test_upgrade_abstains_when_fill_unresolvable(tmp_path, monkeypatch):
    """A fill that has aged out of the broker window (no order_id -> price) must stay honest, never fabricated."""
    ledger = tmp_path / "sleeve_trade_ledger.jsonl"
    _write(ledger, [_close_row("xs_momentum", "IWM", 2, 200.0, "2026-08-08T14:30:05")])
    monkeypatch.setattr(SleeveTradeLedgerEngine, "LEDGER", ledger)

    from app.services import execution_log_engine as xmod
    monkeypatch.setattr(xmod.ExecutionLogEngine, "_intents",
                        lambda self: [{"strategy": "xs_momentum", "symbol": "IWM", "action": "SELL",
                                       "qty": 2, "order_id": "OID1", "ts": "2026-08-08T14:30:00"}])
    monkeypatch.setattr(xmod.ExecutionLogEngine, "_broker_fills", lambda self: {})  # aged out

    res = SleeveTradeLedgerEngine().upgrade_close_fills()
    assert res["upgraded"] == 0
    row = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()][0]
    assert row["realized_pnl_basis"] == "quote_estimate"   # untouched, still honest


def test_upgrade_does_not_match_wrong_symbol_or_stale_sell(tmp_path, monkeypatch):
    ledger = tmp_path / "sleeve_trade_ledger.jsonl"
    _write(ledger, [_close_row("xs_momentum", "IWM", 2, 200.0, "2026-08-08T14:30:05")])
    monkeypatch.setattr(SleeveTradeLedgerEngine, "LEDGER", ledger)

    from app.services import execution_log_engine as xmod
    # wrong symbol AND a sell 10 days stale — neither may match
    monkeypatch.setattr(xmod.ExecutionLogEngine, "_intents",
                        lambda self: [{"strategy": "xs_momentum", "symbol": "QQQM", "action": "SELL",
                                       "qty": 2, "order_id": "OID1", "ts": "2026-08-08T14:30:00"},
                                      {"strategy": "xs_momentum", "symbol": "IWM", "action": "SELL",
                                       "qty": 2, "order_id": "OID2", "ts": "2026-07-29T14:30:00"}])
    monkeypatch.setattr(xmod.ExecutionLogEngine, "_broker_fills", lambda self: {"OID1": 300.0, "OID2": 205.0})

    res = SleeveTradeLedgerEngine().upgrade_close_fills()
    assert res["upgraded"] == 0                    # QQQM wrong symbol; IWM sell is outside the 48h window
    row = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()][0]
    assert row["realized_pnl_basis"] == "quote_estimate"


def test_court_flags_estimate_verdict_provisional(tmp_path, monkeypatch):
    """Genuine-ESTIMATE exits -> the verdict carries PROVISIONAL and the estimate/confirmed split is exposed.

    Hybrid model (2026-08-11): a sleeve-ledger close is broker-confirmed-QUANTITY by construction, so a
    'quote_estimate' tag now reads back as the confirmation floor 'mark_at_confirm' (counts as confirmed).
    Only a genuine price estimate NOT tied to a confirmed-quantity instant (e.g. a condor 'mid_estimate')
    makes a verdict PROVISIONAL — so that is what this exercises."""
    ledger = tmp_path / "sleeve_trade_ledger.jsonl"
    rows = [_close_row("low_vol", "USMV", 3, 80.0, f"2026-08-0{d}T14:30:05", basis="mid_estimate")
            for d in range(1, 6)]
    _write(ledger, rows)
    monkeypatch.setattr(EdgePersistenceEngine, "SLEEVE_LEDGER", ledger)
    # isolate: point the other ledgers at empty temp files so only low_vol trades exist
    for attr in ("VRP_LEDGER", "OPT_LEDGER", "EQ_LEDGER"):
        p = tmp_path / f"{attr}.jsonl"
        p.write_text("")
        monkeypatch.setattr(EdgePersistenceEngine, attr, p)

    lv = (EdgePersistenceEngine().realized_edge().get("sleeves") or {}).get("low_vol") or {}
    assert lv.get("estimated_trades") == 5
    assert lv.get("fill_confirmed_trades") == 0
    assert "PROVISIONAL" in lv.get("verdict", "")
    assert "estimate" in (lv.get("fill_confirmation") or "").lower()


def test_court_confirmed_exits_not_flagged_provisional(tmp_path, monkeypatch):
    ledger = tmp_path / "sleeve_trade_ledger.jsonl"
    rows = [_close_row("low_vol", "USMV", 3, 80.0, f"2026-08-0{d}T14:30:05", basis="fills") for d in range(1, 6)]
    _write(ledger, rows)
    monkeypatch.setattr(EdgePersistenceEngine, "SLEEVE_LEDGER", ledger)
    for attr in ("VRP_LEDGER", "OPT_LEDGER", "EQ_LEDGER"):
        p = tmp_path / f"{attr}.jsonl"
        p.write_text("")
        monkeypatch.setattr(EdgePersistenceEngine, attr, p)

    lv = (EdgePersistenceEngine().realized_edge().get("sleeves") or {}).get("low_vol") or {}
    assert lv.get("estimated_trades") == 0
    assert lv.get("fill_confirmed_trades") == 5
    assert "PROVISIONAL" not in lv.get("verdict", "")
