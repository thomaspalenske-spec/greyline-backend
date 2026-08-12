"""Periodic-return track: low-turnover sleeves (trend long/flat, managed_futures monthly) close ~quarterly,
so a close-based day-gate is structurally unreachable. They're verdicted instead on NON-OVERLAPPING periodic
book returns (return-on-deployed) from SLEEVE-ATTRIBUTED book marks — rebalance-flow periods excluded, same
rigorous verdict_from_returns bar. Fully hermetic: no broker, no orders."""

import json

from app.services.edge_persistence_engine import EdgePersistenceEngine as E
from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine as L


def _marks(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _row(date, dep, unr, sleeve="trend"):
    return {"date": date, "sleeve": sleeve, "deployed": dep, "unrealized": unr,
            "book_value": dep + unr, "ts": date + "T16:00:00"}


def test_no_flow_periods_are_mark_to_market_returns(tmp_path, monkeypatch):
    bm = tmp_path / "bm.jsonl"
    # weekly endpoints (7 days apart), deployed stable -> pure MTM return = Δunrealized / deployed_start
    _marks(bm, [_row("2026-01-01", 1000.0, 0.0), _row("2026-01-08", 1000.0, 10.0),
                _row("2026-01-15", 1000.0, 25.0), _row("2026-01-22", 1000.0, 45.0)])
    monkeypatch.setattr(E, "BOOK_MARKS", bm)
    rets, meta = E()._periodic_returns("trend", 7)
    assert rets == [0.01, 0.015, 0.02] and meta["flow_skipped"] == 0 and meta["marks"] == 4


def test_rebalance_flow_period_is_excluded(tmp_path, monkeypatch):
    bm = tmp_path / "bm.jsonl"
    # deployed jumps 1000 -> 1500 between wk1 and wk2 (a rebalance flow) -> that period is dropped, and the
    # next period measures on the NEW deployed base (1500), never counting the cash flow as a return
    _marks(bm, [_row("2026-01-01", 1000.0, 0.0), _row("2026-01-08", 1000.0, 10.0),
                _row("2026-01-15", 1500.0, 12.0), _row("2026-01-22", 1500.0, 30.0)])
    monkeypatch.setattr(E, "BOOK_MARKS", bm)
    rets, meta = E()._periodic_returns("trend", 7)
    assert meta["flow_skipped"] == 1
    assert rets == [0.01, round((30.0 - 12.0) / 1500.0, 10)] or (
        abs(rets[0] - 0.01) < 1e-9 and abs(rets[1] - 0.012) < 1e-9)


def test_trend_gets_a_periodic_verdict_not_a_close_gate(tmp_path, monkeypatch):
    bm = tmp_path / "bm.jsonl"
    # 22 weekly marks, deployed stable, steady +0.7%/0.9% alternating on 1000 -> 21 returns, mean 0.8% > floor
    rows, unr = [], 0.0
    for i in range(22):
        d = f"2026-{1 + i // 4:02d}-{1 + (i % 4) * 7:02d}"   # ~weekly, distinct buckets
        rows.append(_row(d, 1000.0, unr))
        unr += 7.0 if i % 2 == 0 else 9.0
    _marks(bm, rows)
    monkeypatch.setattr(E, "BOOK_MARKS", bm)
    monkeypatch.setattr(E, "_closed_trades", lambda self: ([], 0))    # no closed trades anywhere
    out = E().realized_edge()
    tr = out["sleeves"]["trend"]
    assert tr["measurement"] == "periodic_return_on_deployed" and tr["period"] == "weekly"
    assert tr["independent_days"] == 21                              # 21 non-overlapping weekly obs
    assert tr["verdict"].startswith("PROVEN") and "PERIODIC" in tr["verdict"]
    assert tr["risk_basis"] == "return_on_deployed"
    assert out["periodic_gate"] == E.PERIODIC_MIN_PERIODS


def test_too_few_periods_is_accumulating(tmp_path, monkeypatch):
    bm = tmp_path / "bm.jsonl"
    _marks(bm, [_row("2026-01-01", 1000.0, 0.0), _row("2026-01-08", 1000.0, 5.0)])
    monkeypatch.setattr(E, "BOOK_MARKS", bm)
    monkeypatch.setattr(E, "_closed_trades", lambda self: ([], 0))
    tr = E().realized_edge()["sleeves"]["trend"]
    assert tr["independent_days"] == 1 and "ACCUMULATING" in tr["verdict"] and "PERIODIC" in tr["verdict"]


def test_book_marks_are_sleeve_attributed_not_symbol(tmp_path, monkeypatch):
    # trend and xs_momentum BOTH hold QQQM; the book mark must count trend's OWN 10 shares, not the shared 15
    monkeypatch.setattr(L, "LEDGER", tmp_path / "sleeve.jsonl")
    led = L()
    led.reconcile("trend", "QQQM", 10, 100.0)
    led.reconcile("xs_momentum", "QQQM", 5, 100.0)
    assert led.open_positions("trend") == {"QQQM": {"qty": 10.0, "cost": 1000.0}}   # not 15

    bm = tmp_path / "bm.jsonl"
    monkeypatch.setattr(E, "BOOK_MARKS", bm)
    monkeypatch.setattr(E, "PERIODIC_SLEEVES", {"trend": 7})
    import app.services.sleeve_trade_ledger_engine as lmod
    monkeypatch.setattr(lmod.SleeveTradeLedgerEngine, "LEDGER", tmp_path / "sleeve.jsonl")
    positions = [{"symbol": "QQQM", "current_price": 105.0}]
    r = E().record_sleeve_book_marks(positions)
    assert r["status"] == "BOOK_MARKS_RECORDED"
    row = json.loads(bm.read_text().splitlines()[-1])
    assert row["sleeve"] == "trend" and row["deployed"] == 1000.0 and row["book_value"] == 1050.0
    assert row["unrealized"] == 50.0            # 10 * (105 - 100), trend's own lot only


def test_missing_price_skips_never_fabricates(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LEDGER", tmp_path / "sleeve.jsonl")
    L().reconcile("trend", "QQQM", 10, 100.0)
    bm = tmp_path / "bm.jsonl"
    monkeypatch.setattr(E, "BOOK_MARKS", bm)
    monkeypatch.setattr(E, "PERIODIC_SLEEVES", {"trend": 7})
    import app.services.sleeve_trade_ledger_engine as lmod
    monkeypatch.setattr(lmod.SleeveTradeLedgerEngine, "LEDGER", tmp_path / "sleeve.jsonl")
    r = E().record_sleeve_book_marks([{"symbol": "SPY", "current_price": 500.0}])   # QQQM price missing
    assert r["status"] == "BOOK_MARKS_RECORDED" and r["sleeves"] == {}              # trend skipped, no row
    assert not bm.exists() or bm.read_text().strip() == ""
