import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.strategy_validation_engine import StrategyValidationEngine

MOD = "app.services.strategy_validation_engine"
FAV = "FAVORABLE_EXECUTE_SIGNAL"
UNF = "UNFAVORABLE_EXECUTE_SIGNAL"


def _o(result, direction, decision="EXECUTE", move=0.0):
    return {"score_status": "SCORED", "score_result": result, "directional_bias": direction,
            "decision": decision, "move_pct": move}


def _make(n, result, direction, decision="EXECUTE"):
    return [_o(result, direction, decision) for _ in range(n)]


def _validate(outcomes, execute_only=True):
    with patch(f"{MOD}.DecisionOutcomeScoringEngine") as MockScore:
        MockScore.return_value.score.return_value = {"scored_outcomes": outcomes}
        return StrategyValidationEngine().validate(execute_only=execute_only)


def test_insufficient_data_when_few_execute_trades():
    out = _make(5, FAV, "BULLISH") + _make(5, UNF, "BEARISH")
    assert _validate(out)["verdict"] == "INSUFFICIENT_DATA"


def test_drift_confound_detected_when_directions_diverge():
    # bullish all win, bearish all lose -> market drift, not skill
    out = _make(20, FAV, "BULLISH") + _make(20, UNF, "BEARISH")
    r = _validate(out)
    assert r["verdict"] == "MEASUREMENT_CONFOUNDED_BY_DRIFT"
    assert r["per_direction"]["bullish"]["hit_rate"] == 1.0
    assert r["per_direction"]["bearish"]["hit_rate"] == 0.0


def test_edge_confirmed_when_both_directions_skilled():
    # both sides ~70% (no straddle) -> real edge
    out = (_make(28, FAV, "BULLISH") + _make(12, UNF, "BULLISH")
           + _make(28, FAV, "BEARISH") + _make(12, UNF, "BEARISH"))
    r = _validate(out)
    assert r["verdict"] == "EDGE_CONFIRMED"
    assert r["hit_rate_test"]["p_value_two_sided"] < 0.05


def test_inverse_when_both_directions_wrong():
    out = (_make(12, FAV, "BULLISH") + _make(28, UNF, "BULLISH")
           + _make(12, FAV, "BEARISH") + _make(28, UNF, "BEARISH"))
    r = _validate(out)
    assert r["verdict"] == "SIGNIFICANT_INVERSE_SIGNAL"


def test_no_significant_edge_near_coin_flip():
    out = (_make(21, FAV, "BULLISH") + _make(19, UNF, "BULLISH")
           + _make(21, FAV, "BEARISH") + _make(19, UNF, "BEARISH"))
    r = _validate(out)
    assert r["verdict"] == "NO_SIGNIFICANT_EDGE"


def test_execute_only_filter_excludes_watch():
    # plentiful WATCH, but almost no EXECUTE -> still INSUFFICIENT under execute_only
    out = _make(200, FAV, "BULLISH", decision="WATCH") + _make(4, FAV, "BULLISH", decision="EXECUTE")
    assert _validate(out, execute_only=True)["verdict"] == "INSUFFICIENT_DATA"
    assert _validate(out, execute_only=True)["population"] == "EXECUTE_ONLY"


def test_measurement_method_caveat_present():
    r = _validate(_make(20, FAV, "BULLISH") + _make(20, UNF, "BEARISH"))
    assert "drift-confounded" in r["measurement_method"]
