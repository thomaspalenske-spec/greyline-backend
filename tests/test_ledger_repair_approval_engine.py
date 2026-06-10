import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ledger_repair_approval_engine import (
    LedgerRepairApprovalEngine
)


def test_approve_single_candidate():

    candidates = [
        {
            "index": 1,
            "proposed_trade_id": "GL-REPAIRED-0001"
        },
        {
            "index": 2,
            "proposed_trade_id": "GL-REPAIRED-0002"
        }
    ]

    result = (
        LedgerRepairApprovalEngine()
        .approve(
            candidates,
            approved_indexes=[1]
        )
    )

    assert result["approved_count"] == 1
    assert (
        result["approved_candidates"][0]["proposed_trade_id"]
        == "GL-REPAIRED-0001"
    )


def test_approve_none():

    candidates = [
        {
            "index": 1,
            "proposed_trade_id": "GL-REPAIRED-0001"
        }
    ]

    result = (
        LedgerRepairApprovalEngine()
        .approve(
            candidates,
            approved_indexes=[]
        )
    )

    assert result["approved_count"] == 0
