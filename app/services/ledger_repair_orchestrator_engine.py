from datetime import datetime

from app.services.ledger_repair_candidate_engine import LedgerRepairCandidateEngine
from app.services.ledger_repair_approval_engine import LedgerRepairApprovalEngine
from app.services.ledger_repair_engine import LedgerRepairEngine
from app.services.ledger_post_repair_validation_engine import (
    LedgerPostRepairValidationEngine
)
from app.services.ledger_repair_audit_engine import (
    LedgerRepairAuditEngine
)


class LedgerRepairOrchestratorEngine:

    def repair(self, approved_indexes):

        candidates = (
            LedgerRepairCandidateEngine()
            .generate_candidates()
        )

        approved = (
            LedgerRepairApprovalEngine()
            .approve(
                candidates.get("candidates", []),
                approved_indexes
            )
        )

        repair = (
            LedgerRepairEngine()
            .repair(
                approved.get(
                    "approved_candidates",
                    []
                )
            )
        )

        validation = (
            LedgerPostRepairValidationEngine()
            .validate()
        )

        LedgerRepairAuditEngine().record(
            repair_candidates=
                approved.get(
                    "approved_candidates",
                    []
                ),
            repairs_applied=
                repair.get(
                    "repairs_applied",
                    0
                )
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "candidate_count":
                candidates.get(
                    "candidate_count",
                    0
                ),
            "approved_count":
                approved.get(
                    "approved_count",
                    0
                ),
            "repairs_applied":
                repair.get(
                    "repairs_applied",
                    0
                ),
            "validation_status":
                validation.get(
                    "status"
                ),
            "status":
                "LEDGER_REPAIR_WORKFLOW_COMPLETE"
        }
