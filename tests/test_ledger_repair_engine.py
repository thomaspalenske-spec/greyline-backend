import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ledger_repair_engine import (
    LedgerRepairEngine
)


def test_repair_assigns_trade_id():

    ledger = {
        "trades": [
            {
                "symbol": "NVDA",
                "state": "ACTIVE"
            }
        ]
    }

    approved = [
        {
            "index": 0,
            "proposed_trade_id":
                "GL-REPAIRED-0000"
        }
    ]

    with patch(
        "app.services.ledger_repair_engine.LedgerEngine"
    ) as MockLedger:

        instance = MockLedger.return_value

        instance.load.return_value = ledger

        result = (
            LedgerRepairEngine()
            .repair(approved)
        )

        saved_ledger = (
            instance.save.call_args[0][0]
        )

    assert (
        saved_ledger["trades"][0]["trade_id"]
        == "GL-REPAIRED-0000"
    )

    assert result["repairs_applied"] == 1


def test_repair_skips_existing_trade_id():

    ledger = {
        "trades": [
            {
                "trade_id": "GL-1",
                "symbol": "NVDA"
            }
        ]
    }

    approved = [
        {
            "index": 0,
            "proposed_trade_id":
                "GL-REPAIRED-0000"
        }
    ]

    with patch(
        "app.services.ledger_repair_engine.LedgerEngine"
    ) as MockLedger:

        instance = MockLedger.return_value

        instance.load.return_value = ledger

        result = (
            LedgerRepairEngine()
            .repair(approved)
        )

    assert result["repairs_applied"] == 0
