from datetime import datetime


class LedgerRepairApprovalEngine:

    def approve(
        self,
        candidates,
        approved_indexes
    ):

        approved = []

        for candidate in candidates:

            if candidate.get("index") in approved_indexes:
                approved.append(candidate)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "approved_count": len(approved),
            "approved_candidates": approved,
            "status": "LEDGER_REPAIR_APPROVED"
        }
