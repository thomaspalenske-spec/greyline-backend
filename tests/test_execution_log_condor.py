"""Condor execution slippage into ExecutionLog: record_fill logs a completed net-slippage entry (the
multi-leg order id can't join to one fill), and realized() aggregates it per premium sleeve."""

from app.services.execution_log_engine import ExecutionLogEngine as L


def test_record_fill_direct_slippage(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "DIR", tmp_path)
    monkeypatch.setattr(L, "LEDGER", tmp_path / "intent.jsonl")
    monkeypatch.setattr(L, "_broker_fills", lambda self: {})     # hermetic: no broker call
    eng = L()
    # closed a condor: net mid debit .30, actual fill debit .38 -> paid worse than mid (a cost)
    eng.record_fill("premium_vrp", "XLE", "BUY", 100, mid=0.30, fill=0.38)
    by = eng.realized()["by_strategy"]
    assert "premium_vrp" in by
    v = by["premium_vrp"]
    assert v["orders"] == 1 and v["filled"] == 1 and v["fill_rate_pct"] == 100.0
    assert v["avg_slippage_bps"] > 0                              # + = paid worse than mid
    assert v["realized_slippage_usd"] == 8.0                      # (.38-.30) * 100


def test_direct_and_joined_entries_coexist(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "DIR", tmp_path)
    monkeypatch.setattr(L, "LEDGER", tmp_path / "intent.jsonl")
    monkeypatch.setattr(L, "_broker_fills", lambda self: {"O-1": 100.5})  # a joined equity fill
    eng = L()
    eng.record("trend", "QQQM", "BUY", 1, 100.4, 100.3, 100.5, "O-1")     # intent-only (joins to O-1)
    eng.record_fill("premium_earnings", "STRL", "BUY", 100, mid=0.40, fill=0.40)  # direct, zero slip
    by = eng.realized()["by_strategy"]
    assert by["trend"]["filled"] == 1                            # joined fill worked
    assert by["premium_earnings"]["filled"] == 1 and by["premium_earnings"]["avg_slippage_bps"] == 0.0
