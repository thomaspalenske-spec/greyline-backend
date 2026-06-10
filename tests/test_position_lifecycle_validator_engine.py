import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.position_lifecycle_validator_engine import PositionLifecycleValidatorEngine


def test_valid_position_lifecycle_passes():
    events = [
        {"trade_id": "GL-1", "event_type": "trade_created"},
        {"trade_id": "GL-1", "event_type": "trade_updated"},
        {"trade_id": "GL-1", "event_type": "trade_closed"},
    ]

    result = PositionLifecycleValidatorEngine().validate_lifecycle(events)

    assert result["valid"] is True
    assert result["status"] == "POSITION_LIFECYCLE_VALID"


def test_close_before_create_fails():
    events = [
        {"trade_id": "GL-1", "event_type": "trade_closed"},
    ]

    result = PositionLifecycleValidatorEngine().validate_lifecycle(events)

    assert result["valid"] is False
    assert result["errors"][0]["reason"] == "close_before_create"


def test_update_after_close_fails():
    events = [
        {"trade_id": "GL-1", "event_type": "trade_created"},
        {"trade_id": "GL-1", "event_type": "trade_closed"},
        {"trade_id": "GL-1", "event_type": "trade_updated"},
    ]

    result = PositionLifecycleValidatorEngine().validate_lifecycle(events)

    assert result["valid"] is False
    assert result["errors"][0]["reason"] == "update_after_close"


def test_duplicate_close_fails():
    events = [
        {"trade_id": "GL-1", "event_type": "trade_created"},
        {"trade_id": "GL-1", "event_type": "trade_closed"},
        {"trade_id": "GL-1", "event_type": "trade_closed"},
    ]

    result = PositionLifecycleValidatorEngine().validate_lifecycle(events)

    assert result["valid"] is False
    assert result["errors"][0]["reason"] == "duplicate_trade_closed"
