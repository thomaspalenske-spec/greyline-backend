"""Regression tests for the measurement defects found in the 2026-07-20 audit.

Each of these encodes a bug that made GreyLine report an edge it did not have. None of them
were caught by the existing suite — the subsystem whose job is preventing self-deception
had no tests covering the ways it deceived itself.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.price_history_store import PriceHistoryStore


# --------------------------------------------------------------------------- price_at

def _store(tmp_path, symbol, points):
    s = PriceHistoryStore(base_dir=str(tmp_path))
    for ts, px in points:
        s.record(symbol, px, timestamp=ts)
    return s


def test_price_at_before_never_returns_a_future_price(tmp_path):
    """An ENTRY price sampled after the decision leaks the outcome into the entry and
    manufactures skill on any momentum-derived signal."""
    s = _store(tmp_path, "AAA", [
        ("2026-06-15T10:00:00", 100.0),
        ("2026-06-15T11:00:00", 130.0),      # the move we must not see at entry
    ])
    hit = s.price_at("AAA", "2026-06-15T10:30:00", max_tolerance_seconds=3600,
                     direction="before")
    assert hit["price"] == 100.0
    assert hit["is_after"] is False
    assert hit["age_seconds"] < 0            # signed: negative means "before"


def test_price_at_after_never_returns_a_past_price(tmp_path):
    """An OUTCOME price sampled early shortens the horizon it claims to measure."""
    s = _store(tmp_path, "AAA", [
        ("2026-06-15T10:00:00", 100.0),
        ("2026-06-15T11:00:00", 130.0),
    ])
    hit = s.price_at("AAA", "2026-06-15T10:30:00", max_tolerance_seconds=3600,
                     direction="after")
    assert hit["price"] == 130.0
    assert hit["is_after"] is True
    assert hit["age_seconds"] > 0


def test_price_at_nearest_still_matches_either_side(tmp_path):
    s = _store(tmp_path, "AAA", [("2026-06-15T10:00:00", 100.0)])
    assert s.price_at("AAA", "2026-06-15T10:10:00", max_tolerance_seconds=3600)["price"] == 100.0


def test_price_at_returns_none_when_the_constrained_side_is_empty(tmp_path):
    s = _store(tmp_path, "AAA", [("2026-06-15T11:00:00", 130.0)])
    assert s.price_at("AAA", "2026-06-15T10:00:00", max_tolerance_seconds=3600,
                      direction="before") is None


# ------------------------------------------------------- open positions / equity truth

def test_open_losers_reduce_equity(monkeypatch, tmp_path):
    """The defect: the summary summed `unrealized_pnl`, a field open_trade() never writes,
    so it was structurally zero and an open position contributed nothing however far
    underwater. Close the winners, hold the losers, and equity only ever rose."""
    from app.services import paper_performance_summary_engine as mod

    store = _store(tmp_path, "LOSS", [("2026-06-15T20:00:00", 50.0)])
    monkeypatch.setattr(
        "app.services.price_history_store.PriceHistoryStore",
        lambda *a, **k: store)

    eng = mod.PaperPerformanceSummaryEngine()
    pnl, unvalued = eng._mark_open_positions(
        [{"symbol": "LOSS", "entry_price": 100.0, "quantity": 2, "side": "BUY"}])
    assert unvalued == []
    assert pnl == -100.0, "a position halved must show a loss, not zero"


def test_short_positions_profit_when_price_falls(monkeypatch, tmp_path):
    from app.services import paper_performance_summary_engine as mod
    store = _store(tmp_path, "SHRT", [("2026-06-15T20:00:00", 50.0)])
    monkeypatch.setattr(
        "app.services.price_history_store.PriceHistoryStore", lambda *a, **k: store)
    pnl, _ = mod.PaperPerformanceSummaryEngine()._mark_open_positions(
        [{"symbol": "SHRT", "entry_price": 100.0, "quantity": 2, "side": "SELL"}])
    assert pnl == 100.0


def test_unpriceable_position_makes_equity_unknown_not_flat(monkeypatch, tmp_path):
    """Reporting equity that silently omits an unpriceable position is the failure being
    removed. Unknown must be None with a reason, not a confident number."""
    from app.services import paper_performance_summary_engine as mod
    store = _store(tmp_path, "OTHER", [("2026-06-15T20:00:00", 50.0)])
    monkeypatch.setattr(
        "app.services.price_history_store.PriceHistoryStore", lambda *a, **k: store)
    pnl, unvalued = mod.PaperPerformanceSummaryEngine()._mark_open_positions(
        [{"symbol": "NOPRICE", "entry_price": 100.0, "quantity": 1, "side": "BUY"}])
    assert unvalued == ["NOPRICE"]


# ---------------------------------------------------------------- fixed-horizon capture

def _ledger(tmp_path, rows):
    p = tmp_path / "opportunity_outcome_ledger.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def test_decision_younger_than_the_horizon_is_pending_not_scored(tmp_path, monkeypatch):
    """The defect: outcomes were `live_quote / snapshot_price`, so the holding period was
    the gap until the grader happened to run — minutes, sometimes. Every row scored."""
    from app.services.forward_outcome_capture_engine import ForwardOutcomeCaptureEngine

    now = datetime.utcnow()
    eng = ForwardOutcomeCaptureEngine(horizon_hours=24)
    eng.ledger_file = _ledger(tmp_path, [{
        "timestamp": (now - timedelta(hours=1)).isoformat(),
        "symbol": "AAA", "snapshot_price": 100.0, "directional_bias": "BULLISH"}])
    eng.price_store = _store(tmp_path, "AAA", [(now.isoformat(), 150.0)])
    eng._last_price = lambda s: {"symbol": s, "price": 150.0, "is_delayed": False,
                                 "trade_time": now.isoformat(), "quote_status": "OK"}

    out = eng.capture(limit=10)
    assert out["outcomes"][0]["outcome_state"] == "PENDING_HORIZON_NOT_REACHED"
    assert out["scored_count"] == 0
    assert out["outcomes"][0]["directional_return_pct"] is None


def test_matured_decision_is_scored_against_the_horizon_price_not_the_live_quote(tmp_path):
    from app.services.forward_outcome_capture_engine import ForwardOutcomeCaptureEngine

    t0 = datetime(2026, 6, 15, 14, 0, 0)
    eng = ForwardOutcomeCaptureEngine(horizon_hours=24)
    eng.ledger_file = _ledger(tmp_path, [{
        "timestamp": t0.isoformat(), "symbol": "AAA",
        "snapshot_price": 100.0, "directional_bias": "BULLISH"}])
    # The T-1h point is CLOSER to the target than the T+2h one, so a two-sided "nearest"
    # match would grab 105 — a price from before the horizon was reached. Only a forward
    # constrained match returns 110. The live quote of 999 must be ignored entirely.
    eng.price_store = _store(tmp_path, "AAA", [
        ((t0 + timedelta(hours=23)).isoformat(), 105.0),
        ((t0 + timedelta(hours=26)).isoformat(), 110.0),
        ((t0 + timedelta(days=30)).isoformat(), 999.0),
    ])
    eng._last_price = lambda s: {"symbol": s, "price": 999.0, "is_delayed": True,
                                 "trade_time": None, "quote_status": "OK"}

    row = eng.capture(limit=10)["outcomes"][0]
    assert row["outcome_state"] == "PRICE_CAPTURED"
    assert row["outcome_price"] == 110.0
    assert row["raw_return_pct"] == 10.0, "scored against the live quote, not T+horizon"


def test_capture_surfaces_sample_independence(tmp_path):
    """50 ledger rows have been as few as 2 symbols over 5 hours. Anything computing a win
    rate must be able to see that rather than dividing by len(outcomes)."""
    from app.services.forward_outcome_capture_engine import ForwardOutcomeCaptureEngine

    t0 = datetime(2026, 6, 15, 14, 0, 0)
    rows = [{"timestamp": (t0 + timedelta(minutes=5 * i)).isoformat(),
             "symbol": "AAA" if i % 2 else "BBB",
             "snapshot_price": 100.0, "directional_bias": "BULLISH"} for i in range(20)]
    eng = ForwardOutcomeCaptureEngine(horizon_hours=24)
    eng.ledger_file = _ledger(tmp_path, rows)
    eng.price_store = _store(tmp_path, "AAA", [(t0.isoformat(), 100.0)])
    eng._last_price = lambda s: {"symbol": s, "price": 100.0, "is_delayed": True,
                                 "trade_time": None, "quote_status": "OK"}

    out = eng.capture(limit=50)
    assert out["records_checked"] == 20
    assert out["distinct_symbols"] == 2
    assert out["distinct_decision_days"] == 1
