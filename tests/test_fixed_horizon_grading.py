import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.price_history_store import PriceHistoryStore
from app.services.fixed_horizon_grader_engine import FixedHorizonGraderEngine


# ---- PriceHistoryStore ----
def test_record_and_price_at_nearest(tmp_path):
    s = PriceHistoryStore(base_dir=tmp_path / "ph")
    s.record("NVDA", 100.0, "2026-07-01T10:00:00")
    s.record("NVDA", 110.0, "2026-07-02T10:00:00")
    s.record("NVDA", 120.0, "2026-07-03T10:00:00")

    hit = s.price_at("NVDA", "2026-07-02T10:05:00", max_tolerance_seconds=3600)
    assert hit is not None and hit["price"] == 110.0


def test_price_at_returns_none_outside_tolerance(tmp_path):
    s = PriceHistoryStore(base_dir=tmp_path / "ph")
    s.record("NVDA", 100.0, "2026-07-01T10:00:00")
    assert s.price_at("NVDA", "2026-07-05T10:00:00", max_tolerance_seconds=3600) is None


def test_rejects_bad_prices(tmp_path):
    s = PriceHistoryStore(base_dir=tmp_path / "ph")
    assert s.record("NVDA", 0) is False
    assert s.record("NVDA", "abc") is False
    assert s.coverage("NVDA")["points"] == 0


# ---- FixedHorizonGraderEngine (drift-free) ----
def _decisions():
    # A BULLISH call at T with price 100; a later snapshot at T+24h shows 105 (+5%).
    # A BEARISH put at T with price 100; T+24h shows 105 -> bad for bearish.
    return [
        {"symbol": "AAA", "snapshot_price": 100.0, "timestamp": "2026-07-01T10:00:00", "directional_bias": "BULLISH", "result": "EXECUTE"},
        {"symbol": "AAA", "snapshot_price": 105.0, "timestamp": "2026-07-02T10:00:00", "directional_bias": "BULLISH", "result": "EXECUTE"},
        {"symbol": "BBB", "snapshot_price": 100.0, "timestamp": "2026-07-01T10:00:00", "directional_bias": "BEARISH", "result": "EXECUTE"},
        {"symbol": "BBB", "snapshot_price": 105.0, "timestamp": "2026-07-02T10:00:00", "directional_bias": "BEARISH", "result": "EXECUTE"},
    ]


def test_grades_at_fixed_horizon(tmp_path):
    g = FixedHorizonGraderEngine(horizon_hours=24, tolerance_hours=6)
    g.store = PriceHistoryStore(base_dir=tmp_path / "ph")  # empty; index comes from decisions
    r = g.grade(decisions=_decisions())

    # AAA bullish: +5% over horizon -> FAVORABLE. BBB bearish: price rose -> UNFAVORABLE.
    assert r["counts"]["FAVORABLE"] == 1
    assert r["counts"]["UNFAVORABLE"] == 1
    graded = {x["symbol"]: x for x in r["graded"]}
    assert graded["AAA"]["grade"] == "FAVORABLE"
    assert graded["BBB"]["grade"] == "UNFAVORABLE"


def test_decision_without_matured_forward_price_is_pending(tmp_path):
    g = FixedHorizonGraderEngine(horizon_hours=24, tolerance_hours=6)
    g.store = PriceHistoryStore(base_dir=tmp_path / "ph")
    # Single decision, no later snapshot within tolerance of T+24h -> PENDING.
    r = g.grade(decisions=[_decisions()[0]])
    assert r["counts"]["PENDING_NO_FORWARD_PRICE"] == 1
    assert r["graded_count"] == 0


def test_uses_persistent_store_for_forward_price(tmp_path):
    g = FixedHorizonGraderEngine(horizon_hours=24, tolerance_hours=6)
    g.store = PriceHistoryStore(base_dir=tmp_path / "ph")
    g.store.record("CCC", 110.0, "2026-07-02T10:00:00")  # forward price only in the store
    r = g.grade(decisions=[
        {"symbol": "CCC", "snapshot_price": 100.0, "timestamp": "2026-07-01T10:00:00", "directional_bias": "BULLISH", "result": "EXECUTE"},
    ])
    assert r["counts"]["FAVORABLE"] == 1  # +10% bullish, graded off the store point
