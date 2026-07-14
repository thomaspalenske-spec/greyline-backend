import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.decision_outcome_scoring_engine import DecisionOutcomeScoringEngine

MODULE = "app.services.decision_outcome_scoring_engine"


def _score(outcomes):
    with patch(f"{MODULE}.ForwardOutcomeCaptureEngine") as MockCapture:
        MockCapture.return_value.capture.return_value = {"outcomes": outcomes}
        return DecisionOutcomeScoringEngine().score()


def _outcome(**kw):
    base = {
        "symbol": "NVDA",
        "candidate_result": "EXECUTE",
        "candidate_timestamp": "2026-07-11T12:00:00",
        "timestamp": "2026-07-11T13:00:00",
        "directional_bias": "BULLISH",
        "outcome_state": "PRICE_CAPTURED",
        "directional_return_pct": 0.0,
        "snapshot_price": 100.0,
        "current_price": 100.0,
    }
    base.update(kw)
    return base


def test_reads_outcomes_key_not_stale_captures_key():
    # The core regression: capture() emits "outcomes"; the engine used to read
    # "captures" and scored nothing. A favorable outcome must now be counted.
    result = _score([_outcome(directional_return_pct=2.5)])

    assert result["events_analyzed"] == 1
    assert result["favorable_count"] == 1
    assert result["scored_outcomes"][0]["score_result"] == "FAVORABLE_EXECUTE_SIGNAL"


def test_classification_bands():
    result = _score([
        _outcome(directional_return_pct=1.0),    # favorable (>= +1)
        _outcome(directional_return_pct=-1.0),   # unfavorable (<= -1)
        _outcome(directional_return_pct=0.4),    # neutral
    ])

    assert result["favorable_count"] == 1
    assert result["unfavorable_count"] == 1
    assert result["neutral_count"] == 1


def test_price_unavailable_is_skipped():
    result = _score([_outcome(outcome_state="PRICE_UNAVAILABLE")])

    assert result["skipped_count"] == 1
    assert result["scored_outcomes"][0]["score_status"] == "SKIPPED"


def test_non_directional_outcome_is_pending():
    # No directional bias -> capture() leaves directional_return_pct None.
    result = _score([_outcome(directional_bias=None, directional_return_pct=None)])

    assert result["pending_count"] == 1
    assert result["scored_outcomes"][0]["score_status"] == "PENDING"


def test_output_contract_keys_preserved_for_downstream():
    # decision_accuracy_dashboard / decision_learning / feature_attribution read
    # these exact keys and score_result strings.
    item = _score([_outcome(directional_return_pct=3.0)])["scored_outcomes"][0]

    for key in ("decision_timestamp", "symbol", "decision", "move_pct", "score_result", "score_status"):
        assert key in item
    assert item["score_result"] == "FAVORABLE_EXECUTE_SIGNAL"


def test_empty_when_no_ledger():
    result = _score([])

    assert result["events_analyzed"] == 0
    assert result["status"] == "DECISION_OUTCOME_SCORING_READY"
