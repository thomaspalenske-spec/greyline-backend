import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ledger_repair_candidate_engine import LedgerRepairCandidateEngine


def test_repair_candidates_created_for_missing_trade_id():
    report = {
        "status": "LEDGER_QUARANTINE_REQUIRED",
        "quarantined": [
            {
                "index": 1,
                "trade": {"symbol": "NVDA"},
                "reasons": ["MISSING_TRADE_ID"]
            }
        ]
    }

    with patch("app.services.ledger_repair_candidate_engine.LedgerQuarantineReportEngine") as MockReport:
        MockReport.return_value.generate.return_value = report

        result = LedgerRepairCandidateEngine().generate_candidates()

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["proposed_trade_id"] == "GL-REPAIRED-0001"
    assert result["candidates"][0]["requires_manual_approval"] is True


def test_no_candidates_when_ledger_clean():
    report = {
        "status": "LEDGER_CLEAN",
        "quarantined": []
    }

    with patch("app.services.ledger_repair_candidate_engine.LedgerQuarantineReportEngine") as MockReport:
        MockReport.return_value.generate.return_value = report

        result = LedgerRepairCandidateEngine().generate_candidates()

    assert result["candidate_count"] == 0
    assert result["status"] == "NO_LEDGER_REPAIR_CANDIDATES"
