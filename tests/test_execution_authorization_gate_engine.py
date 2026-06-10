import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.execution_authorization_gate_engine import ExecutionAuthorizationGateEngine


def test_execution_authorized_for_green_paper_mode():
    dashboard = {
        "health_level": "GREEN",
        "integrity_pass": True
    }

    result = ExecutionAuthorizationGateEngine().authorize(
        dashboard,
        requested_mode="paper"
    )

    assert result["execution_authorized"] is True
    assert result["status"] == "EXECUTION_AUTHORIZED_PAPER"


def test_execution_denied_when_health_not_green():
    dashboard = {
        "health_level": "YELLOW",
        "integrity_pass": True
    }

    result = ExecutionAuthorizationGateEngine().authorize(
        dashboard,
        requested_mode="paper"
    )

    assert result["execution_authorized"] is False
    assert "GOVERNANCE_NOT_GREEN" in result["authorization_reasons"]
    assert result["status"] == "EXECUTION_DENIED"


def test_execution_denied_when_integrity_fails():
    dashboard = {
        "health_level": "GREEN",
        "integrity_pass": False
    }

    result = ExecutionAuthorizationGateEngine().authorize(
        dashboard,
        requested_mode="paper"
    )

    assert result["execution_authorized"] is False
    assert "INTEGRITY_NOT_PASSED" in result["authorization_reasons"]


def test_live_mode_always_denied():
    dashboard = {
        "health_level": "GREEN",
        "integrity_pass": True
    }

    result = ExecutionAuthorizationGateEngine().authorize(
        dashboard,
        requested_mode="live"
    )

    assert result["execution_authorized"] is False
    assert result["status"] == "EXECUTION_DENIED"
