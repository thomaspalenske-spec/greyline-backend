import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.forecast_outcome_capture_engine import ForecastOutcomeCaptureEngine
from app.services.forward_outcome_capture_engine import ForwardOutcomeCaptureEngine
from app.services.price_history_store import PriceHistoryStore
from app.services.data_integrity_engine import DataIntegrityEngine


# ---- dedup: score wiggle must not fragment one standing forecast ----

def test_capture_dedup_ignores_score_wiggle_within_bucket():
    now = datetime(2026, 7, 14, 16, 3, 0)
    base = {"symbol": "SPY", "directional_bias": "BULLISH", "option_type": "CALL",
            "result": "WATCH", "regime": "WEAK_LIVE"}

    k1 = ForecastOutcomeCaptureEngine._capture_dedupe_key({**base, "composite_score": 86.59}, now)
    k2 = ForecastOutcomeCaptureEngine._capture_dedupe_key(
        {**base, "composite_score": 86.61}, now.replace(minute=12))

    # Same directional call for the same symbol in the same 15-min bucket = one observation.
    assert k1 == k2


def test_capture_dedup_still_separates_real_differences():
    now = datetime(2026, 7, 14, 16, 3, 0)
    base = {"symbol": "SPY", "option_type": "CALL", "result": "WATCH",
            "regime": "WEAK_LIVE", "composite_score": 86.0}

    bull = ForecastOutcomeCaptureEngine._capture_dedupe_key({**base, "directional_bias": "BULLISH"}, now)
    bear = ForecastOutcomeCaptureEngine._capture_dedupe_key({**base, "directional_bias": "BEARISH"}, now)
    later = ForecastOutcomeCaptureEngine._capture_dedupe_key(
        {**base, "directional_bias": "BULLISH"}, now.replace(minute=31))

    assert bull != bear           # opposite calls are distinct
    assert bull != later          # a different 15-min bucket is a new observation


# ---- forward price feed: the fuel the grader was missing ----

def test_forward_capture_records_price_points(tmp_path):
    ledger = tmp_path / "opportunity_outcome_ledger.jsonl"
    import json
    ledger.write_text(json.dumps({
        "symbol": "SPY", "snapshot_price": 500.0, "directional_bias": "BULLISH",
        "timestamp": "2026-07-14T16:00:00",
    }) + "\n")

    eng = ForwardOutcomeCaptureEngine()
    eng.ledger_file = ledger
    eng.price_store = PriceHistoryStore(base_dir=str(tmp_path / "ph"))

    with patch.object(eng, "_last_price", return_value={
        "symbol": "SPY", "price": 505.0, "quote_status": "OK",
        "trade_time": "2026-07-14T16:05:00", "is_delayed": False,
    }):
        out = eng.capture(limit=60)

    assert out["price_points_recorded"] == 1
    assert eng.price_store.coverage("SPY")["points"] == 1


def test_forward_capture_skips_delayed_quotes(tmp_path):
    # A stale/delayed quote is not a valid forward price and must not pollute the series.
    ledger = tmp_path / "l.jsonl"
    import json
    ledger.write_text(json.dumps({"symbol": "SPY", "snapshot_price": 500.0,
                                  "directional_bias": "BULLISH", "timestamp": "2026-07-14T16:00:00"}) + "\n")
    eng = ForwardOutcomeCaptureEngine()
    eng.ledger_file = ledger
    eng.price_store = PriceHistoryStore(base_dir=str(tmp_path / "ph"))

    with patch.object(eng, "_last_price", return_value={
        "symbol": "SPY", "price": 505.0, "is_delayed": True, "trade_time": None,
    }):
        out = eng.capture(limit=60)

    assert out["price_points_recorded"] == 0


# ---- data integrity verdict ----

def test_integrity_is_red_on_too_few_days(monkeypatch):
    grades = [{
        "forecast_correct": True, "symbol": "SPY", "snapshot_price": 500.0,
        "predicted_direction": "BULLISH", "candidate_timestamp": "2026-07-14T16:00:00",
    }] * 3  # all one day

    monkeypatch.setattr("app.services.data_integrity_engine.read_jsonl",
                        lambda p: grades if "grades" in str(p) else [])
    monkeypatch.setattr(DataIntegrityEngine, "GRADES", Path("grades.jsonl"))

    with patch("app.services.data_integrity_engine.FixedHorizonGraderEngine") as MockFH:
        MockFH.return_value.grade.return_value = {
            "horizon_hours": 24, "counts": {"PENDING_NO_FORWARD_PRICE": 0},
            "graded_count": 3, "balanced_accuracy_precision_based": 0.5, "skill": {"mcc": 0.0},
        }
        out = DataIntegrityEngine().diagnose()

    assert out["verdict"] == "RED"
    assert out["independence"]["distinct_days"] == 1
    assert any("distinct day" in r for r in out["reasons"])
