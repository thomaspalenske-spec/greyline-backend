import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_trading_control_center_engine import PaperTradingControlCenterEngine

MODULE = "app.services.paper_trading_control_center_engine"


def _run(balance_ok, positions_ok, credentials_configured):
    with patch(f"{MODULE}.GreyLineReliabilityCoreEngine") as MockReliability, \
         patch(f"{MODULE}.ApiCredentialReadinessEngine") as MockCredentials:
        MockReliability.return_value.evaluate.return_value = {
            "checks": {"balance_ok": balance_ok, "positions_ok": positions_ok},
        }
        MockCredentials.return_value.evaluate_credentials.return_value = {
            "api_credentials_configured": credentials_configured,
        }
        return PaperTradingControlCenterEngine().get_control_center()


def test_broker_connected_and_credentials_configured_reflected_as_true():
    result = _run(balance_ok=True, positions_ok=True, credentials_configured=True)

    assert result["broker_connected"] is True
    assert result["api_credentials_configured"] is True


def test_broker_not_connected_when_balance_read_fails():
    result = _run(balance_ok=False, positions_ok=True, credentials_configured=True)

    assert result["broker_connected"] is False


def test_broker_not_connected_when_positions_read_fails():
    result = _run(balance_ok=True, positions_ok=False, credentials_configured=True)

    assert result["broker_connected"] is False


def test_credentials_not_configured_reflected_as_false():
    result = _run(balance_ok=True, positions_ok=True, credentials_configured=False)

    assert result["api_credentials_configured"] is False


def test_governance_gates_remain_locked_regardless_of_connectivity():
    # Broker reachable + creds set must NOT arm paper trading. Those gates are
    # deliberate human-controlled decisions, not derived from connectivity.
    result = _run(balance_ok=True, positions_ok=True, credentials_configured=True)

    assert result["paper_trading_ready"] is False
    assert result["paper_trading_blocked"] is True
    assert result["approval_passed"] is False
    assert result["authority_level"] == "OBSERVE_RECOMMEND_ONLY"
    assert result["status"] == "PAPER_TRADING_CONTROL_CENTER_ACTIVE"


def test_missing_checks_key_defaults_to_not_connected():
    # Defensive: if the reliability core payload lacks a checks block, the
    # control center must fail closed rather than raise.
    with patch(f"{MODULE}.GreyLineReliabilityCoreEngine") as MockReliability, \
         patch(f"{MODULE}.ApiCredentialReadinessEngine") as MockCredentials:
        MockReliability.return_value.evaluate.return_value = {}
        MockCredentials.return_value.evaluate_credentials.return_value = {}
        result = PaperTradingControlCenterEngine().get_control_center()

    assert result["broker_connected"] is False
    assert result["api_credentials_configured"] is False
