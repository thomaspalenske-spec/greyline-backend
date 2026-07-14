import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.execution_governor import ExecutionGovernor

MODULE = "app.services.execution_governor"


def _evaluate(env):
    # Patch os.getenv as seen inside execution_governor to the provided mapping,
    # so an absent key returns the caller-supplied default (fail-safe behavior).
    def fake_getenv(key, default=None):
        return env.get(key, default)

    with patch(f"{MODULE}.getenv", side_effect=fake_getenv):
        return ExecutionGovernor().evaluate_execution_permission("EXECUTE")


def test_unset_paper_flag_defaults_to_blocked():
    # The whole point of the change: no flag set => execution is NOT armed.
    result = _evaluate({})

    assert result["paper_execution_enabled"] is False
    assert result["execution_enabled"] is False
    assert result["order_placement_allowed"] is False


def test_explicit_true_arms_paper_execution():
    result = _evaluate({"GREYLINE_PAPER_EXECUTION_ENABLED": "true"})

    assert result["paper_execution_enabled"] is True
    assert result["execution_enabled"] is True
    assert result["order_placement_allowed"] is True


def test_explicit_false_blocks_paper_execution():
    result = _evaluate({"GREYLINE_PAPER_EXECUTION_ENABLED": "false"})

    assert result["paper_execution_enabled"] is False
    assert result["order_placement_allowed"] is False


def test_case_insensitive_true():
    result = _evaluate({"GREYLINE_PAPER_EXECUTION_ENABLED": "TRUE"})

    assert result["paper_execution_enabled"] is True


def test_live_flags_remain_failsafe_false_by_default():
    result = _evaluate({"GREYLINE_PAPER_EXECUTION_ENABLED": "true"})

    assert result["live_trading_enabled"] is False
    assert result["live_order_placement_allowed"] is False
