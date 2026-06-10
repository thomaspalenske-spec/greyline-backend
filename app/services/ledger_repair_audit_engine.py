from datetime import datetime

from app.services.immutable_audit_ledger_engine import (
    ImmutableAuditLedgerEngine
)


class LedgerRepairAuditEngine:

    def record(
        self,
        repair_candidates,
        repairs_applied
    ):

        ImmutableAuditLedgerEngine().record(
            "LEDGER_REPAIR",
            {
                "repairs_applied": repairs_applied,
                "repair_candidates": repair_candidates
            }
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "repairs_applied": repairs_applied,
            "audit_recorded": True,
            "status": "LEDGER_REPAIR_AUDITED"
        }
