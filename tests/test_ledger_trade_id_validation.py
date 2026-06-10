import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ledger_engine import LedgerEngine


def test_trade_without_trade_id_is_rejected(tmp_path):
    engine = LedgerEngine()

    engine.ledger_path = tmp_path / "ledger.json"
    engine.save({"trades": []})

    result = engine.add_trade(
        {
            "symbol": "NVDA"
        }
    )

    assert result["trade_saved"] is False
    assert result["reason"] == "missing_trade_id"


def test_duplicate_trade_id_is_rejected(tmp_path):
    engine = LedgerEngine()

    engine.ledger_path = tmp_path / "ledger.json"
    engine.save(
        {
            "trades": [
                {
                    "trade_id": "GL-TEST-0001"
                }
            ]
        }
    )

    result = engine.add_trade(
        {
            "trade_id": "GL-TEST-0001"
        }
    )

    assert result["trade_saved"] is False
    assert result["reason"] == "duplicate_trade_id"


def test_unique_trade_id_is_saved(tmp_path):
    engine = LedgerEngine()

    engine.ledger_path = tmp_path / "ledger.json"
    engine.save({"trades": []})

    result = engine.add_trade(
        {
            "trade_id": "GL-TEST-0002"
        }
    )

    assert result["trade_saved"] is True
    assert result["trade_id"] == "GL-TEST-0002"
