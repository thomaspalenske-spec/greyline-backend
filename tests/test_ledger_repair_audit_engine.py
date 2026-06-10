import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ledger_repair_audit_engine import (
    LedgerRepairAuditEngine
)


def test_repair_audit_recorded():

    with patch(
        "app.services.ledger_repair_audit_engine.ImmutableAuditLedgerEngine"
    ) as MockAudit:

        result = (
            LedgerRepairAuditEngine()
            .record(
                repair_candidates=[
                    {"index": 1}
                ],
                repairs_applied=1
            )
        )

        MockAudit.return_value.record.assert_called_once()

    assert result["audit_recorded"] is True
    assert result["status"] == "LEDGER_REPAIR_AUDITED"
