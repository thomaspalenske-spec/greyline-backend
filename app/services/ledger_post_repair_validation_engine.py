from datetime import datetime

from app.services.ledger_quarantine_report_engine import (
    LedgerQuarantineReportEngine
)


class LedgerPostRepairValidationEngine:

    def validate(self):
        report = LedgerQuarantineReportEngine().generate()

        clean = report.get("quarantined_count", 0) == 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "ledger_clean": clean,
            "quarantined_count": report.get("quarantined_count", 0),
            "quarantine_status": report.get("status"),
            "status": (
                "LEDGER_POST_REPAIR_VALIDATION_PASS"
                if clean
                else "LEDGER_POST_REPAIR_VALIDATION_FAIL"
            )
        }
