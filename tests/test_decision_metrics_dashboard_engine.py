import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.decision_metrics_dashboard_engine import DecisionMetricsDashboardEngine

MODULE = "app.services.decision_metrics_dashboard_engine"


def _summarize(favorable, unfavorable, neutral):
    with patch(f"{MODULE}.DecisionSelfAuditEngine") as MockAudit, \
         patch(f"{MODULE}.DecisionOutcomeScoringEngine") as MockScoring:
        MockAudit.return_value.analyze.return_value = {
            "decision_performance": {"events_analyzed": 10, "execute_signal_count": 4, "no_action_count": 6},
            "decision_outcomes": {"execute_signal_pending_validation": 1},
        }
        MockScoring.return_value.score.return_value = {
            "favorable_count": favorable,
            "unfavorable_count": unfavorable,
            "neutral_count": neutral,
        }
        return DecisionMetricsDashboardEngine().summarize()


def test_quality_is_none_when_nothing_scored():
    # The core fix: no scored outcomes must NOT report a fabricated perfect 100.
    result = _summarize(0, 0, 0)
    assert result["decision_quality_score"] is None


def test_all_favorable_is_100():
    assert _summarize(4, 0, 0)["decision_quality_score"] == 100.0


def test_all_unfavorable_is_0():
    assert _summarize(0, 4, 0)["decision_quality_score"] == 0.0


def test_neutral_counts_half():
    # 1 favorable, 1 neutral, 2 unfavorable -> (1 + 0.5) / 4 = 37.5
    assert _summarize(1, 2, 1)["decision_quality_score"] == 37.5


def test_basis_is_surfaced_for_transparency():
    basis = _summarize(2, 1, 1)["decision_quality_basis"]
    assert basis["favorable"] == 2
    assert basis["scored"] == 4
    assert "formula" in basis


def test_passthrough_audit_fields_preserved():
    result = _summarize(1, 0, 0)
    assert result["events_analyzed"] == 10
    assert result["execute_signals"] == 4
    assert result["no_actions"] == 6
    assert result["pending_validation"] == 1
    assert result["status"] == "DECISION_METRICS_READY"
