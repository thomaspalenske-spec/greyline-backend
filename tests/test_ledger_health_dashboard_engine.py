import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ledger_health_dashboard_engine import LedgerHealthDashboardEngine


def test_ledger_health_dashboard_reports_repair_required():
    with patch("app.services.ledger_health_dashboard_engine.LedgerQuarantineReportEngine") as MockQuarantine, \
         patch("app.services.ledger_health_dashboard_engine.LedgerRepairCandidateEngine") as MockCandidates, \
         patch("app.services.ledger_health_dashboard_engine.LedgerPostRepairValidationEngine") as MockValidation:

        MockQuarantine.return_value.generate.return_value = {
            "status": "LEDGER_QUARANTINE_REQUIRED",
            "quarantined_count": 3
        }

        MockCandidates.return_value.generate_candidates.return_value = {
            "candidate_count": 3
        }

        MockValidation.return_value.validate.return_value = {
            "status": "LEDGER_POST_REPAIR_VALIDATION_FAIL"
        }

        result = LedgerHealthDashboardEngine().get_dashboard()

    assert result["ledger_clean"] is False
    assert result["repair_ready"] is True
    assert result["status"] == "LEDGER_REPAIR_REQUIRED"


def test_ledger_health_dashboard_reports_healthy():
    with patch("app.services.ledger_health_dashboard_engine.LedgerQuarantineReportEngine") as MockQuarantine, \
         patch("app.services.ledger_health_dashboard_engine.LedgerRepairCandidateEngine") as MockCandidates, \
         patch("app.services.ledger_health_dashboard_engine.LedgerPostRepairValidationEngine") as MockValidation:

        MockQuarantine.return_value.generate.return_value = {
            "status": "LEDGER_CLEAN",
            "quarantined_count": 0
        }

        MockCandidates.return_value.generate_candidates.return_value = {
            "candidate_count": 0
        }

        MockValidation.return_value.validate.return_value = {
            "status": "LEDGER_POST_REPAIR_VALIDATION_PASS"
        }

        result = LedgerHealthDashboardEngine().get_dashboard()

    assert result["ledger_clean"] is True
    assert result["repair_ready"] is False
    assert result["status"] == "LEDGER_HEALTHY"
