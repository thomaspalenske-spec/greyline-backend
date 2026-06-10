import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_position_manager_engine import PaperPositionManagerEngine


def test_get_active_positions_returns_only_active_trades():
    trades = [
        {"trade_id": "GL-1", "state": "ACTIVE"},
        {"trade_id": "GL-2", "state": "CLOSED"},
    ]

    with patch("app.services.paper_position_manager_engine.LedgerEngine") as MockLedger:
        MockLedger.return_value.get_all_trades.return_value = trades

        result = PaperPositionManagerEngine().get_active_positions()

    assert result["position_count"] == 1
    assert result["positions"][0]["trade_id"] == "GL-1"
    assert result["status"] == "ACTIVE_POSITIONS_LOADED"


def test_close_position_updates_matching_trade():
    ledger = {
        "trades": [
            {"trade_id": "GL-1", "state": "ACTIVE"}
        ]
    }

    with patch("app.services.paper_position_manager_engine.LedgerEngine") as MockLedger:
        mock_instance = MockLedger.return_value
        mock_instance.load.return_value = ledger

        result = PaperPositionManagerEngine().close_position("GL-1")

        mock_instance.save.assert_called_once()

    assert result["position_closed"] is True
    assert ledger["trades"][0]["state"] == "CLOSED"
    assert result["status"] == "POSITION_CLOSED"


def test_close_position_returns_not_found_for_missing_trade():
    ledger = {
        "trades": [
            {"trade_id": "GL-1", "state": "ACTIVE"}
        ]
    }

    with patch("app.services.paper_position_manager_engine.LedgerEngine") as MockLedger:
        mock_instance = MockLedger.return_value
        mock_instance.load.return_value = ledger

        result = PaperPositionManagerEngine().close_position("GL-999")

        mock_instance.save.assert_not_called()

    assert result["position_closed"] is False
    assert result["status"] == "POSITION_NOT_FOUND"
