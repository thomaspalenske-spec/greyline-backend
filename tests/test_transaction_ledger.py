"""Rolling 2-day transaction ledger: today's running tally + the most-recent prior session, with anything
older dropped. It rolls purely off the ET date + ledger timestamps — no persistence, no nightly shift."""

from datetime import datetime, timedelta
from app.services.transaction_ledger_engine import TransactionLedgerEngine as T


def test_rolling_buckets_and_dropoff(monkeypatch):
    eng = T()
    today = datetime.now(eng.MARKET_TZ).date()

    def iso(d):
        return f"{d.isoformat()}T15:00:00"      # 15:00 UTC -> same ET calendar date (EDT/EST)

    events = [
        {"ts": iso(today), "sleeve": "vrp_condor", "symbol": "QQQ", "action": "OPEN", "quantity": 1, "detail": "c", "pnl": None},
        {"ts": iso(today), "sleeve": "earnings", "symbol": "XLE", "action": "CLOSE", "quantity": 1, "detail": "tp", "pnl": 50.0},
        {"ts": iso(today - timedelta(days=1)), "sleeve": "momentum", "symbol": "GLW", "action": "CLOSE", "quantity": 2, "detail": "stop", "pnl": -10.0},
        {"ts": iso(today - timedelta(days=3)), "sleeve": "momentum", "symbol": "OLD", "action": "OPEN", "quantity": 1, "detail": "x", "pnl": None},
    ]
    monkeypatch.setattr(T, "_events", lambda self: events)
    r = eng.rolling()

    # today = running tally of today's txns
    assert r["today"]["count"] == 2 and r["today"]["realized_pnl"] == 50.0
    assert r["today"]["realized_label"] == "running"
    assert {t["symbol"] for t in r["today"]["transactions"]} == {"QQQ", "XLE"}

    # yesterday = MOST RECENT prior session (skips gaps), older drops off
    assert r["yesterday"]["date"] == (today - timedelta(days=1)).isoformat()
    assert r["yesterday"]["count"] == 1 and r["yesterday"]["realized_pnl"] == -10.0
    shown = {t["symbol"] for b in ("today", "yesterday") for t in r[b]["transactions"]}
    assert "OLD" not in shown          # 3-days-ago dropped


def test_etf_sleeve_trades_from_execlog_included_no_double_count(monkeypatch, tmp_path):
    """Direct-to-broker ETF sleeves' trades come from the ExecutionLog; momentum + condors (already in the
    equity/condor ledgers) and direct-fill entries are excluded so nothing double-counts. Regression for the
    '0 txn today' while the ETF sleeves actively traded."""
    import json
    eng = T()
    for attr in ("EQUITY_LEDGER", "VRP_LEDGER", "OPT_LEDGER"):
        monkeypatch.setattr(T, attr, tmp_path / f"{attr}.jsonl")
    monkeypatch.setattr(T, "EXEC_LEDGER", tmp_path / "exec.jsonl")
    (tmp_path / "exec.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"ts": "2026-08-05T13:42:00", "strategy": "low_vol", "symbol": "USMV", "action": "BUY", "qty": 3, "limit": 100.0},
        {"ts": "2026-08-05T13:42:00", "strategy": "carry", "symbol": "SVXY", "action": "SELL", "qty": 48, "limit": 58.0},
        {"ts": "2026-08-05T13:42:00", "strategy": "momentum", "symbol": "AAPL", "action": "BUY", "qty": 1, "limit": 200.0},
        {"ts": "2026-08-05T13:42:00", "strategy": "premium_earnings", "symbol": "CLX", "action": "SELL", "qty": 1, "direct": True},
    ]))
    ev = eng._events()
    syms = {e["symbol"] for e in ev}
    assert "USMV" in syms and "SVXY" in syms          # ETF sleeves appear
    assert "AAPL" not in syms                         # momentum NOT double-counted from the exec log
    assert "CLX" not in syms                          # condor / direct-fill entry excluded
    lv = next(e for e in ev if e["symbol"] == "USMV")
    assert lv["action"] == "BUY" and lv["sleeve"] == "low_vol" and lv["pnl"] is None


def test_empty_ledgers_are_safe(monkeypatch):
    monkeypatch.setattr(T, "_events", lambda self: [])
    r = T().rolling()
    assert r["today"]["count"] == 0 and r["yesterday"]["count"] == 0
    assert r["yesterday"]["date"] is None and r["status"] == "TRANSACTIONS_ROLLING_READY"
