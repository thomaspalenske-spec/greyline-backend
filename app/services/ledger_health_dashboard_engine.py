from datetime import datetime

from app.services.ledger_quarantine_report_engine import LedgerQuarantineReportEngine
from app.services.ledger_repair_candidate_engine import LedgerRepairCandidateEngine
from app.services.ledger_post_repair_validation_engine import LedgerPostRepairValidationEngine


class LedgerHealthDashboardEngine:

    def get_dashboard(self):
        quarantine = LedgerQuarantineReportEngine().generate()
        candidates = LedgerRepairCandidateEngine().generate_candidates()
        validation = LedgerPostRepairValidationEngine().validate()

        ledger_clean = quarantine.get("quarantined_count", 0) == 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "ledger_clean": ledger_clean,
            "quarantine_status": quarantine.get("status"),
            "quarantined_count": quarantine.get("quarantined_count", 0),
            "repair_candidate_count": candidates.get("candidate_count", 0),
            "post_repair_validation_status": validation.get("status"),
            "repair_ready": candidates.get("candidate_count", 0) > 0,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LEDGER_HEALTHY" if ledger_clean else "LEDGER_REPAIR_REQUIRED"
        }
