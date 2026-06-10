import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ledger_repair_orchestrator_engine import (
    LedgerRepairOrchestratorEngine
)


def test_orchestrator_workflow_complete():

    with patch(
        "app.services.ledger_repair_orchestrator_engine.LedgerRepairCandidateEngine"
    ) as MockCandidates, \
    patch(
        "app.services.ledger_repair_orchestrator_engine.LedgerRepairApprovalEngine"
    ) as MockApproval, \
    patch(
        "app.services.ledger_repair_orchestrator_engine.LedgerRepairEngine"
    ) as MockRepair, \
    patch(
        "app.services.ledger_repair_orchestrator_engine.LedgerPostRepairValidationEngine"
    ) as MockValidation, \
    patch(
        "app.services.ledger_repair_orchestrator_engine.LedgerRepairAuditEngine"
    ) as MockAudit:

        MockCandidates.return_value.generate_candidates.return_value = {
            "candidate_count": 3,
            "candidates": [{"index": 1}]
        }

        MockApproval.return_value.approve.return_value = {
            "approved_count": 1,
            "approved_candidates": [{"index": 1}]
        }

        MockRepair.return_value.repair.return_value = {
            "repairs_applied": 1
        }

        MockValidation.return_value.validate.return_value = {
            "status": "LEDGER_POST_REPAIR_VALIDATION_PASS"
        }

        result = (
            LedgerRepairOrchestratorEngine()
            .repair([1])
        )

    assert result["candidate_count"] == 3
    assert result["approved_count"] == 1
    assert result["repairs_applied"] == 1
    assert result["status"] == "LEDGER_REPAIR_WORKFLOW_COMPLETE"

    MockAudit.return_value.record.assert_called_once()
