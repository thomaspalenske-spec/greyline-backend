"""Tests for the 'make governance surfaces honest' batch (#1, #4, #10)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---- #1: prep-gate reflects real readiness, not hardcoded True ----
def test_prep_gate_passes_only_when_all_real_signals_ready():
    import app.routes.paper_trading as pt

    ready = {
        "broker_sandbox_connected": True,
        "api_credentials_configured": True,
        "manual_approval_granted": True,
        "kill_switch_testing_complete": True,
    }
    with patch.object(pt, "PaperTradingBlockerEngine") as MockBlocker, \
         patch.object(pt, "GreyLineReliabilityCoreEngine") as MockReliability:
        MockBlocker.return_value.evaluate_blockers.return_value = {"readiness": ready}
        MockReliability.return_value.evaluate.return_value = {"status": "RELIABILITY_CORE_HEALTHY"}
        result = pt.paper_trading_prep_gate()

    assert result["prep_gate_passed"] is True
    assert result["next_mode"] == "PAPER_TRADING_PREP"


def test_prep_gate_blocks_when_a_real_signal_is_missing():
    import app.routes.paper_trading as pt

    ready = {
        "broker_sandbox_connected": False,   # not ready
        "api_credentials_configured": True,
        "manual_approval_granted": True,
        "kill_switch_testing_complete": True,
    }
    with patch.object(pt, "PaperTradingBlockerEngine") as MockBlocker, \
         patch.object(pt, "GreyLineReliabilityCoreEngine") as MockReliability:
        MockBlocker.return_value.evaluate_blockers.return_value = {"readiness": ready}
        MockReliability.return_value.evaluate.return_value = {"status": "RELIABILITY_CORE_HEALTHY"}
        result = pt.paper_trading_prep_gate()

    assert result["prep_gate_passed"] is False
    assert result["broker_safety_ready"] is False


def test_prep_gate_blocks_when_backend_unhealthy():
    import app.routes.paper_trading as pt

    ready = {
        "broker_sandbox_connected": True,
        "api_credentials_configured": True,
        "manual_approval_granted": True,
        "kill_switch_testing_complete": True,
    }
    with patch.object(pt, "PaperTradingBlockerEngine") as MockBlocker, \
         patch.object(pt, "GreyLineReliabilityCoreEngine") as MockReliability:
        MockBlocker.return_value.evaluate_blockers.return_value = {"readiness": ready}
        MockReliability.return_value.evaluate.return_value = {"status": "RELIABILITY_CORE_DEGRADED"}
        result = pt.paper_trading_prep_gate()

    assert result["backend_ready"] is False
    assert result["prep_gate_passed"] is False


# ---- #4: command center derives factual fields from real engines ----
def test_command_center_reflects_real_broker_and_credentials():
    MOD = "app.services.paper_trading_command_center_engine"
    from app.services.paper_trading_command_center_engine import PaperTradingCommandCenterEngine

    with patch(f"{MOD}.GreyLineReliabilityCoreEngine") as MockReliability, \
         patch(f"{MOD}.ApiCredentialReadinessEngine") as MockCreds:
        MockReliability.return_value.evaluate.return_value = {
            "checks": {"balance_ok": True, "positions_ok": True}
        }
        MockCreds.return_value.evaluate_credentials.return_value = {"api_credentials_configured": True}
        result = PaperTradingCommandCenterEngine().get_command_center()

    assert result["broker_connected"] is True
    assert result["api_credentials_configured"] is True
    # Arming gates remain deliberately locked.
    assert result["paper_trading_blocked"] is True
    assert result["authority_level"] == "OBSERVE_RECOMMEND_ONLY"


def test_command_center_broker_disconnected_when_reads_fail():
    MOD = "app.services.paper_trading_command_center_engine"
    from app.services.paper_trading_command_center_engine import PaperTradingCommandCenterEngine

    with patch(f"{MOD}.GreyLineReliabilityCoreEngine") as MockReliability, \
         patch(f"{MOD}.ApiCredentialReadinessEngine") as MockCreds:
        MockReliability.return_value.evaluate.return_value = {
            "checks": {"balance_ok": False, "positions_ok": True}
        }
        MockCreds.return_value.evaluate_credentials.return_value = {"api_credentials_configured": False}
        result = PaperTradingCommandCenterEngine().get_command_center()

    assert result["broker_connected"] is False
    assert result["api_credentials_configured"] is False


# ---- #10: the dead /governance/status route + PortfolioEngine were removed as
# dead code (router never mounted). No test remains for them here.
