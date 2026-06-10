import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_trade_execution_engine import PaperTradeExecutionEngine


def test_paper_trade_executes_when_request_valid_and_authorized():
    governance_dashboard = {
        "health_level": "GREEN",
        "integrity_pass": True
    }

    with patch("app.services.paper_trade_execution_engine.LedgerEngine") as MockLedger:
        MockLedger.return_value.add_trade.return_value = {
            "trade_saved": True,
            "trade_id": "GL-TEST"
        }

        result = PaperTradeExecutionEngine().execute(
            symbol="NVDA",
            quantity=1,
            order_type="BUY",
            entry_price=100.0,
            governance_dashboard=governance_dashboard
        )

    assert result["paper_trade_executed"] is True
    assert result["status"] == "PAPER_TRADE_EXECUTED"
    assert result["execution_enabled"] is False
    assert result["order_placement_allowed"] is False


def test_paper_trade_rejected_when_request_invalid():
    governance_dashboard = {
        "health_level": "GREEN",
        "integrity_pass": True
    }

    result = PaperTradeExecutionEngine().execute(
        symbol="",
        quantity=1,
        order_type="BUY",
        entry_price=100.0,
        governance_dashboard=governance_dashboard
    )

    assert result["paper_trade_executed"] is False
    assert result["reason"] == "EXECUTION_REQUEST_INVALID"
    assert result["status"] == "PAPER_TRADE_REJECTED"


def test_paper_trade_rejected_when_not_authorized():
    governance_dashboard = {
        "health_level": "YELLOW",
        "integrity_pass": True
    }

    result = PaperTradeExecutionEngine().execute(
        symbol="NVDA",
        quantity=1,
        order_type="BUY",
        entry_price=100.0,
        governance_dashboard=governance_dashboard
    )

    assert result["paper_trade_executed"] is False
    assert result["reason"] == "EXECUTION_NOT_AUTHORIZED"
    assert result["status"] == "PAPER_TRADE_REJECTED"
