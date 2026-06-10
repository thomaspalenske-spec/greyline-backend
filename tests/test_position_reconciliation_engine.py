import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.position_reconciliation_engine import PositionReconciliationEngine


def test_position_reconciliation_passes_valid_ledger():
    ledger = {
        "trades": [
            {"trade_id": "T1", "state": "ACTIVE"},
            {"trade_id": "T2", "state": "CLOSED"},
        ]
    }

    with patch("app.services.position_reconciliation_engine.LedgerEngine") as MockLedger:
        MockLedger.return_value.load.return_value = ledger

        result = PositionReconciliationEngine().reconcile_positions()

    assert result["reconciliation_status"] == "PASS"
    assert result["active_count"] == 1
    assert result["closed_count"] == 1
    assert result["invalid_trade_count"] == 0
    assert result["reconciled"] is True


def test_position_reconciliation_fails_missing_trade_id():
    ledger = {
        "trades": [
            {"state": "ACTIVE"},
        ]
    }

    with patch("app.services.position_reconciliation_engine.LedgerEngine") as MockLedger:
        MockLedger.return_value.load.return_value = ledger

        result = PositionReconciliationEngine().reconcile_positions()

    assert result["reconciliation_status"] == "FAIL"
    assert result["invalid_trade_count"] == 1
    assert result["invalid_trades"][0]["reason"] == "missing_trade_id"


def test_position_reconciliation_fails_invalid_state():
    ledger = {
        "trades": [
            {"trade_id": "T1", "state": "UNKNOWN"},
        ]
    }

    with patch("app.services.position_reconciliation_engine.LedgerEngine") as MockLedger:
        MockLedger.return_value.load.return_value = ledger

        result = PositionReconciliationEngine().reconcile_positions()

    assert result["reconciliation_status"] == "FAIL"
    assert result["invalid_trade_count"] == 1
    assert result["invalid_trades"][0]["reason"] == "invalid_state"
