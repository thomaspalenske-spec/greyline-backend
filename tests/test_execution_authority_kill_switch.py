import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.execution_authority_engine import ExecutionAuthorityEngine

MODULE = "app.services.execution_authority_engine"


def _run(signal, mode, paper_enabled=True, live_enabled=False, live_placement=False):
    with patch(f"{MODULE}.GreyLineMasterDecisionEngine") as MockDecision, \
         patch(f"{MODULE}.ReliabilityGovernorEngine") as MockGovernor, \
         patch(f"{MODULE}.ExecutionGovernor") as MockExecGovernor:
        MockDecision.return_value.evaluate.return_value = {
            "decision": signal,
            "top_candidate": {"symbol": "SPY"},
        }
        MockGovernor.return_value.evaluate.return_value = {
            "operating_mode": mode,
            "reliability_score": 100,
        }
        MockExecGovernor.return_value.evaluate_execution_permission.return_value = {
            "paper_execution_enabled": paper_enabled,
            "live_trading_enabled": live_enabled,
            "live_order_placement_allowed": live_placement,
        }
        return ExecutionAuthorityEngine().evaluate()


def test_paper_execution_allowed_when_flag_enabled_and_signal_executable():
    result = _run("EXECUTE", "PAPER_OPERATIONAL", paper_enabled=True)

    assert result["paper_execution_allowed"] is True
    assert result["execution_authority"] == "PAPER_EXECUTE"


def test_kill_switch_blocks_paper_execution_even_when_signal_and_mode_authorize():
    # The exact scenario from the audit: EXECUTE signal + PAPER_OPERATIONAL, but
    # the env flag is off. Paper execution MUST be denied, not merely reported off.
    result = _run("EXECUTE", "PAPER_OPERATIONAL", paper_enabled=False)

    assert result["paper_execution_allowed"] is False
    assert result["live_execution_allowed"] is False
    assert result["execution_authority"] == "KILL_SWITCH_BLOCKED"
    assert "kill-switch" in result["reason"].lower()


def test_kill_switch_blocks_paper_leg_of_live_mode_when_paper_flag_off():
    # LIVE_OPERATIONAL grants paper_allowed too; the paper kill-switch must still
    # shut everything down when paper execution is disabled.
    result = _run(
        "EXECUTE", "LIVE_OPERATIONAL",
        paper_enabled=False, live_enabled=True, live_placement=True,
    )

    assert result["paper_execution_allowed"] is False
    assert result["live_execution_allowed"] is False
    assert result["execution_authority"] == "KILL_SWITCH_BLOCKED"


def test_live_kill_switch_downgrades_to_paper_when_live_flags_off():
    # Live authorized by mode, but live flags disabled -> keep paper, drop live.
    result = _run(
        "EXECUTE", "LIVE_OPERATIONAL",
        paper_enabled=True, live_enabled=False, live_placement=False,
    )

    assert result["paper_execution_allowed"] is True
    assert result["live_execution_allowed"] is False
    assert result["execution_authority"] == "PAPER_EXECUTE"


def test_live_execution_allowed_when_all_live_flags_enabled():
    result = _run(
        "EXECUTE", "LIVE_OPERATIONAL",
        paper_enabled=True, live_enabled=True, live_placement=True,
    )

    assert result["paper_execution_allowed"] is True
    assert result["live_execution_allowed"] is True
    assert result["execution_authority"] == "LIVE_EXECUTE"


def test_no_executable_signal_stays_no_action_regardless_of_flags():
    result = _run("WATCH", "PAPER_OPERATIONAL", paper_enabled=True)

    assert result["paper_execution_allowed"] is False
    assert result["execution_authority"] == "WATCH"


def test_transparency_fields_reflect_flag_state():
    result = _run("EXECUTE", "PAPER_OPERATIONAL", paper_enabled=False)

    assert result["paper_execution_enabled"] is False
    assert result["live_execution_enabled"] is False
