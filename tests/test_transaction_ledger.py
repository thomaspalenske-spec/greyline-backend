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
        {"ts": "2026-08-05T13:42:00", "strategy": "low_vol", "symbol": "USMV", "action": "BUY", "qty": 3, "limit": 100.0, "order_id": "o1"},
        {"ts": "2026-08-05T13:42:00", "strategy": "carry", "symbol": "SVXY", "action": "SELL", "qty": 48, "limit": 58.0, "order_id": "o1"},
        {"ts": "2026-08-05T13:42:00", "strategy": "momentum", "symbol": "AAPL", "action": "BUY", "qty": 1, "limit": 200.0, "order_id": "o1"},
        {"ts": "2026-08-05T13:42:00", "strategy": "premium_earnings", "symbol": "CLX", "action": "SELL", "qty": 1, "direct": True, "order_id": "o1"},
    ]))
    ev = eng._events()
    syms = {e["symbol"] for e in ev}
    assert "USMV" in syms and "SVXY" in syms          # ETF sleeves appear
    assert "AAPL" not in syms                         # momentum NOT double-counted from the exec log
    assert "CLX" not in syms                          # condor / direct-fill entry excluded
    lv = next(e for e in ev if e["symbol"] == "USMV")
    assert lv["action"] == "BUY" and lv["sleeve"] == "low_vol" and lv["pnl"] is None


def test_etf_sell_realized_pnl_fifo(monkeypatch, tmp_path):
    """ETF SELL rows get realized P&L by FIFO-matching against that sleeve+symbol's own prior BUYs in the
    order log ((sell_px - buy_px) * qty, recorded limit prices -> est). A BUY stays blank; a partial sell
    matches what it can; a sell with NO prior buy stays blank (no basis, not invented). Regression: the
    P/L column read all '—' and yesterday's sells had no basis at all."""
    import json
    eng = T()
    monkeypatch.setattr(T, "_enrich_unrealized", lambda self, bp: bp)     # no broker read in the unit test
    today = datetime.now(eng.MARKET_TZ).date().isoformat()               # date-robust: use TODAY, not a literal
    for attr in ("EQUITY_LEDGER", "VRP_LEDGER", "OPT_LEDGER"):
        monkeypatch.setattr(T, attr, tmp_path / f"{attr}.jsonl")
    monkeypatch.setattr(T, "EXEC_LEDGER", tmp_path / "exec.jsonl")
    (tmp_path / "exec.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"ts": f"{today}T13:40:00", "strategy": "carry", "symbol": "SVXY", "action": "BUY", "qty": 48, "limit": 57.0, "order_id": "o1"},
        {"ts": f"{today}T13:42:00", "strategy": "carry", "symbol": "SVXY", "action": "SELL", "qty": 48, "limit": 58.0, "order_id": "o1"},
        {"ts": f"{today}T13:40:00", "strategy": "trend", "symbol": "IWM", "action": "BUY", "qty": 5, "limit": 300.0, "order_id": "o1"},
        {"ts": f"{today}T13:42:00", "strategy": "trend", "symbol": "IWM", "action": "SELL", "qty": 5, "limit": 303.0, "order_id": "o1"},
        {"ts": f"{today}T13:42:00", "strategy": "momentum", "symbol": "AAPL", "action": "BUY", "qty": 1, "limit": 200.0, "order_id": "o1"},
        {"ts": "2026-08-05T13:42:00", "strategy": "tbill", "symbol": "SGOV", "action": "SELL", "qty": 9, "limit": 100.4, "order_id": "o1"},
    ]))
    ev = {e["symbol"] + ":" + e["action"]: e for e in eng._events()}
    assert ev["SVXY:SELL"]["pnl"] == 48.0 and "est P&L" in ev["SVXY:SELL"]["detail"]   # (58-57)*48
    assert ev["IWM:SELL"]["pnl"] == 15.0                                               # (303-300)*5
    assert ev["SVXY:BUY"]["pnl"] is None            # a buy realizes nothing
    assert ev["SGOV:SELL"]["pnl"] is None           # no prior buy -> no basis, stays blank
    assert "AAPL" not in {e["symbol"] for e in eng._events()}   # momentum still excluded
    r = eng.rolling()
    assert r["today"]["realized_pnl"] == 63.0        # 48 + 15, exact


def test_by_position_nets_churn_into_one_line(monkeypatch):
    """The rebalance churn (many BUY/SELL legs on one name) collapses to ONE netted line per (sleeve,
    symbol) with its total realized P&L — losers first; a name with no P&L-bearing close reads None not 0."""
    eng = T()
    today = datetime.now(eng.MARKET_TZ).date()
    iso = lambda d: f"{d.isoformat()}T15:00:00"
    events = [
        {"ts": iso(today), "sleeve": "carry", "symbol": "SVXY", "action": "BUY", "quantity": 20, "detail": "b", "pnl": None},
        {"ts": iso(today), "sleeve": "carry", "symbol": "SVXY", "action": "SELL", "quantity": 11, "detail": "s", "pnl": 5.0},
        {"ts": iso(today), "sleeve": "carry", "symbol": "SVXY", "action": "SELL", "quantity": 9, "detail": "s", "pnl": -2.0},
        {"ts": iso(today), "sleeve": "earnings", "symbol": "PLTR", "action": "CLOSE", "quantity": 5, "detail": "x", "pnl": -210.0},
        {"ts": iso(today), "sleeve": "low_vol", "symbol": "USMV", "action": "BUY", "quantity": 3, "detail": "b", "pnl": None},
    ]
    monkeypatch.setattr(T, "_events", lambda self: events)
    bypos = {p["symbol"]: p for p in eng.rolling()["today"]["by_position"]}
    assert bypos["SVXY"]["realized_pnl"] == 3.0 and bypos["SVXY"]["fills"] == 3      # 5 - 2, churn netted
    assert bypos["SVXY"]["bought"] == 20 and bypos["SVXY"]["sold"] == 20
    assert bypos["USMV"]["realized_pnl"] is None                                     # buy-only -> None, not 0
    order = [p["symbol"] for p in eng.rolling()["today"]["by_position"]]
    assert order[0] == "PLTR"                                                        # biggest loser first


def test_empty_ledgers_are_safe(monkeypatch):
    monkeypatch.setattr(T, "_events", lambda self: [])
    r = T().rolling()
    assert r["today"]["count"] == 0 and r["yesterday"]["count"] == 0
    assert r["yesterday"]["date"] is None and r["status"] == "TRANSACTIONS_ROLLING_READY"
