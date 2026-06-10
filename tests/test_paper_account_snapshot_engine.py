import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_account_snapshot_engine import PaperAccountSnapshotEngine


def test_snapshot_created_with_positions():
    positions = [
        {
            "symbol": "NVDA",
            "entry_price": 100.0,
            "current_price": 110.0,
            "quantity": 2
        }
    ]

    result = PaperAccountSnapshotEngine().create_snapshot(
        cash_balance=1000.0,
        positions=positions
    )

    assert result["cash_balance"] == 1000.0
    assert result["market_value"] == 220.0
    assert result["equity"] == 1220.0
    assert result["position_count"] == 1
    assert result["status"] == "ACCOUNT_SNAPSHOT_CREATED"


def test_snapshot_created_with_no_positions():
    result = PaperAccountSnapshotEngine().create_snapshot(
        cash_balance=500.0,
        positions=[]
    )

    assert result["cash_balance"] == 500.0
    assert result["market_value"] == 0.0
    assert result["equity"] == 500.0
    assert result["position_count"] == 0
