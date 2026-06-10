import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ledger_quarantine_report_engine import (
    LedgerQuarantineReportEngine
)


def test_ledger_quarantine_flags_missing_trade_id():
    ledger = {
        "trades": [
            {
                "symbol": "NVDA",
                "state": "ACTIVE"
            }
        ]
    }

    with patch(
        "app.services.ledger_quarantine_report_engine.LedgerEngine"
    ) as MockLedger:

        MockLedger.return_value.load.return_value = ledger

        result = LedgerQuarantineReportEngine().generate()

    assert result["status"] == "LEDGER_QUARANTINE_REQUIRED"
    assert result["quarantined_count"] == 1
    assert "MISSING_TRADE_ID" in result["quarantined"][0]["reasons"]


def test_ledger_quarantine_clean_ledger_passes():
    ledger = {
        "trades": [
            {
                "trade_id": "GL-1",
                "symbol": "NVDA",
                "state": "ACTIVE"
            }
        ]
    }

    with patch(
        "app.services.ledger_quarantine_report_engine.LedgerEngine"
    ) as MockLedger:

        MockLedger.return_value.load.return_value = ledger

        result = LedgerQuarantineReportEngine().generate()

    assert result["status"] == "LEDGER_CLEAN"
    assert result["quarantined_count"] == 0
