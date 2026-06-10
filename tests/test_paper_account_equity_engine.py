import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_account_equity_engine import PaperAccountEquityEngine


def test_account_equity_with_positions():
    positions = [
        {
            "symbol": "NVDA",
            "entry_price": 100.0,
            "current_price": 110.0,
            "quantity": 2
        }
    ]

    result = PaperAccountEquityEngine().calculate(
        cash_balance=1000.0,
        positions=positions
    )

    assert result["cash_balance"] == 1000.0
    assert result["market_value"] == 220.0
    assert result["unrealized_pnl"] == 20.0
    assert result["equity"] == 1220.0
    assert result["status"] == "ACCOUNT_EQUITY_CALCULATED"


def test_account_equity_without_positions():
    result = PaperAccountEquityEngine().calculate(
        cash_balance=1000.0,
        positions=[]
    )

    assert result["market_value"] == 0.0
    assert result["unrealized_pnl"] == 0.0
    assert result["equity"] == 1000.0
    assert result["position_count"] == 0
