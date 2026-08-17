"""Realized-slippage reconciliation: fill-vs-mid math, sign (buy/sell), and fill rate."""

from app.services.execution_log_engine import ExecutionLogEngine as E


def _e(monkeypatch, tmp_path, fills):
    monkeypatch.setattr(E, "DIR", tmp_path)
    monkeypatch.setattr(E, "LEDGER", tmp_path / "intent.jsonl")
    monkeypatch.setattr(E, "_broker_fills", lambda self: fills)
    return E()


def test_buy_filled_above_mid_is_a_cost(monkeypatch, tmp_path):
    e = _e(monkeypatch, tmp_path, {"OID1": 100.07})
    e.record("carry", "SVXY", "BUY", 10, 100.07, 100.00, 100.10, "OID1")   # mid 100.05, fill 100.07
    r = e.realized()["by_strategy"]["carry"]
    assert r["orders"] == 1 and r["filled"] == 1 and r["fill_rate_pct"] == 100.0
    assert 1.8 < r["avg_slippage_bps"] < 2.2                 # ~2 bps paid over mid
    assert abs(r["realized_slippage_usd"] - 0.20) < 0.01     # 0.02 x 10 shares


def test_sell_filled_below_mid_is_a_cost(monkeypatch, tmp_path):
    e = _e(monkeypatch, tmp_path, {"OID2": 100.03})
    e.record("trend", "QQQM", "SELL", 5, 100.03, 100.00, 100.10, "OID2")   # mid 100.05, fill 100.03
    r = e.realized()["by_strategy"]["trend"]
    assert r["avg_slippage_bps"] > 0                          # got less than mid -> a cost
    assert abs(r["realized_slippage_usd"] - 0.10) < 0.01      # (100.05-100.03) x 5


def test_unfilled_lowers_fill_rate(monkeypatch, tmp_path):
    e = _e(monkeypatch, tmp_path, {})                        # nothing filled
    e.record("carry", "SVXY", "BUY", 10, 100.05, 100.00, 100.10, "OID3")
    r = e.realized()["by_strategy"]["carry"]
    assert r["orders"] == 1 and r["filled"] == 0 and r["fill_rate_pct"] == 0.0
