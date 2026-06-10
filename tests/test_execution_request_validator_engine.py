import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.execution_request_validator_engine import ExecutionRequestValidatorEngine


def test_valid_execution_request_passes():
    result = ExecutionRequestValidatorEngine().validate(
        symbol="NVDA",
        quantity=1,
        order_type="BUY"
    )

    assert result["valid"] is True
    assert result["status"] == "EXECUTION_REQUEST_VALID"
    assert result["execution_allowed"] is False
    assert result["order_placement_allowed"] is False


def test_missing_symbol_fails():
    result = ExecutionRequestValidatorEngine().validate(
        symbol="",
        quantity=1,
        order_type="BUY"
    )

    assert result["valid"] is False
    assert "MISSING_SYMBOL" in result["errors"]


def test_invalid_quantity_fails():
    result = ExecutionRequestValidatorEngine().validate(
        symbol="NVDA",
        quantity=0,
        order_type="BUY"
    )

    assert result["valid"] is False
    assert "INVALID_QUANTITY" in result["errors"]


def test_invalid_order_type_fails():
    result = ExecutionRequestValidatorEngine().validate(
        symbol="NVDA",
        quantity=1,
        order_type="SHORT"
    )

    assert result["valid"] is False
    assert "INVALID_ORDER_TYPE" in result["errors"]
