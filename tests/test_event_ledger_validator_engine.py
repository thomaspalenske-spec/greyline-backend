import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.event_ledger_validator_engine import EventLedgerValidatorEngine


def test_valid_event_sequence_passes():
    events = [
        {
            "trade_id": "GL-1",
            "event_type": "trade_created",
            "timestamp": "2026-06-10T00:00:00",
            "payload": {}
        },
        {
            "trade_id": "GL-1",
            "event_type": "trade_updated",
            "timestamp": "2026-06-10T00:01:00",
            "payload": {}
        },
        {
            "trade_id": "GL-1",
            "event_type": "trade_closed",
            "timestamp": "2026-06-10T00:02:00",
            "payload": {}
        }
    ]

    result = EventLedgerValidatorEngine().validate_events(events)

    assert result["valid"] is True
    assert result["error_count"] == 0


def test_event_before_trade_created_fails():
    events = [
        {
            "trade_id": "GL-1",
            "event_type": "trade_closed",
            "timestamp": "2026-06-10T00:02:00",
            "payload": {}
        }
    ]

    result = EventLedgerValidatorEngine().validate_events(events)

    assert result["valid"] is False
    assert result["errors"][0]["reason"] == "event_before_trade_created"


def test_duplicate_trade_closed_fails():
    events = [
        {
            "trade_id": "GL-1",
            "event_type": "trade_created",
            "timestamp": "2026-06-10T00:00:00",
            "payload": {}
        },
        {
            "trade_id": "GL-1",
            "event_type": "trade_closed",
            "timestamp": "2026-06-10T00:01:00",
            "payload": {}
        },
        {
            "trade_id": "GL-1",
            "event_type": "trade_closed",
            "timestamp": "2026-06-10T00:02:00",
            "payload": {}
        }
    ]

    result = EventLedgerValidatorEngine().validate_events(events)

    assert result["valid"] is False
    assert result["errors"][0]["reason"] == "duplicate_trade_closed"
