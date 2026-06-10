import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.snapshot_ledger_reconciliation_engine import SnapshotLedgerReconciliationEngine


def test_snapshot_ledger_reconciliation_passes_when_symbols_match():
    ledger = {
        "trades": [
            {"trade_id": "GL-1", "symbol": "NVDA", "state": "ACTIVE"},
            {"trade_id": "GL-2", "symbol": "MSFT", "state": "CLOSED"},
        ]
    }

    snapshot = {
        "positions": [
            {"symbol": "NVDA"}
        ]
    }

    result = SnapshotLedgerReconciliationEngine().reconcile(ledger, snapshot)

    assert result["reconciled"] is True
    assert result["execution_lockout_required"] is False
    assert result["status"] == "SNAPSHOT_LEDGER_RECONCILED"


def test_snapshot_ledger_reconciliation_fails_when_active_ledger_trade_missing_from_snapshot():
    ledger = {
        "trades": [
            {"trade_id": "GL-1", "symbol": "NVDA", "state": "ACTIVE"},
        ]
    }

    snapshot = {
        "positions": []
    }

    result = SnapshotLedgerReconciliationEngine().reconcile(ledger, snapshot)

    assert result["reconciled"] is False
    assert result["execution_lockout_required"] is True
    assert result["missing_from_snapshot"] == ["NVDA"]


def test_snapshot_ledger_reconciliation_fails_when_snapshot_has_unexpected_position():
    ledger = {
        "trades": []
    }

    snapshot = {
        "positions": [
            {"symbol": "TSLA"}
        ]
    }

    result = SnapshotLedgerReconciliationEngine().reconcile(ledger, snapshot)

    assert result["reconciled"] is False
    assert result["execution_lockout_required"] is True
    assert result["unexpected_in_snapshot"] == ["TSLA"]
