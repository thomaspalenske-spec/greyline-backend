import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ledger_post_repair_validation_engine import (
    LedgerPostRepairValidationEngine
)


def test_post_repair_validation_passes_when_ledger_clean():
    with patch(
        "app.services.ledger_post_repair_validation_engine.LedgerQuarantineReportEngine"
    ) as MockReport:

        MockReport.return_value.generate.return_value = {
            "status": "LEDGER_CLEAN",
            "quarantined_count": 0
        }

        result = LedgerPostRepairValidationEngine().validate()

    assert result["ledger_clean"] is True
    assert result["status"] == "LEDGER_POST_REPAIR_VALIDATION_PASS"


def test_post_repair_validation_fails_when_quarantine_remains():
    with patch(
        "app.services.ledger_post_repair_validation_engine.LedgerQuarantineReportEngine"
    ) as MockReport:

        MockReport.return_value.generate.return_value = {
            "status": "LEDGER_QUARANTINE_REQUIRED",
            "quarantined_count": 3
        }

        result = LedgerPostRepairValidationEngine().validate()

    assert result["ledger_clean"] is False
    assert result["status"] == "LEDGER_POST_REPAIR_VALIDATION_FAIL"
