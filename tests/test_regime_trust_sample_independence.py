import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.forecast_regime_trust_engine import ForecastRegimeTrustEngine
from app.services.regime_calibration_engine import RegimeCalibrationEngine


def _trust(tmp_path, rows):
    p = tmp_path / "forecast_outcome_grades.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    eng = ForecastRegimeTrustEngine()
    eng.path = p
    return eng


def _row(symbol, snapshot_price, correct, day="2026-07-13", regime="STRONG_LIVE_TREND"):
    return {
        "regime": regime,
        "symbol": symbol,
        "snapshot_price": snapshot_price,
        "forecast_correct": correct,
        "candidate_timestamp": f"{day}T19:00:00",
    }


# The decision cycle re-forecasts the same symbol many times an hour, so the same market
# moment lands in the grade log repeatedly. Counting those as independent trials is what
# let one bad hour brand STRONG_LIVE_TREND as NEGATIVE_EDGE and veto all trading in it.

def test_same_market_moment_counted_once(tmp_path):
    # One symbol at one price, graded 20 times, is ONE observation — not 20.
    rows = [_row("SPY", 735.37, False) for _ in range(20)]
    out = _trust(tmp_path, rows).evaluate()["regimes"]["STRONG_LIVE_TREND"]

    assert out["sample_size"] == 1
    assert out["incorrect"] == 1


def test_distinct_prices_are_distinct_observations(tmp_path):
    rows = [_row("SPY", 735.37, False), _row("SPY", 736.44, False), _row("SPY", 754.81, True)]
    out = _trust(tmp_path, rows).evaluate()["regimes"]["STRONG_LIVE_TREND"]

    assert out["sample_size"] == 3
    assert out["correct"] == 1


def test_distinct_days_are_tracked(tmp_path):
    rows = [
        _row("SPY", 100.0, False, day="2026-07-13"),
        _row("QQQ", 200.0, False, day="2026-07-13"),
        _row("SPY", 101.0, True, day="2026-07-14"),
    ]
    out = _trust(tmp_path, rows).evaluate()["regimes"]["STRONG_LIVE_TREND"]

    assert out["distinct_days"] == 2
    assert out["sample_size"] == 3


# ---- calibration must not condemn a regime on too few days ----

def _calibrated(monkeypatch, sample_size, distinct_days, accuracy):
    trust = {
        "regimes": {
            "STRONG_LIVE_TREND": {
                "sample_size": sample_size,
                "distinct_days": distinct_days,
                "bayesian_accuracy_pct": accuracy,
            }
        }
    }
    monkeypatch.setattr(
        "app.services.regime_calibration_engine.ForecastRegimeTrustEngine",
        lambda: type("T", (), {"evaluate": staticmethod(lambda: trust)})(),
    )
    return RegimeCalibrationEngine().evaluate("STRONG_LIVE_TREND")


def test_bad_accuracy_on_too_few_days_stays_learning_and_tradeable(monkeypatch):
    # This is the real 2026-07-14 case: plenty of "samples", terrible accuracy, but only
    # 2 days of evidence dominated by a single hour. It must NOT be condemned.
    out = _calibrated(monkeypatch, sample_size=237, distinct_days=2, accuracy=5.26)

    assert out["state"] == "LEARNING"
    assert out["execution_allowed"] is True


def test_bad_accuracy_with_enough_days_still_blocks(monkeypatch):
    # The protection must survive: a regime with genuinely poor edge across enough
    # distinct days is still vetoed.
    out = _calibrated(monkeypatch, sample_size=237, distinct_days=10, accuracy=5.26)

    assert out["state"] == "NEGATIVE_EDGE"
    assert out["execution_allowed"] is False
