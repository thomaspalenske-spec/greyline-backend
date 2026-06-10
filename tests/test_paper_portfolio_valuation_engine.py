import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_portfolio_valuation_engine import PaperPortfolioValuationEngine


def test_portfolio_valuation_calculates_single_position():
    positions = [
        {
            "symbol": "NVDA",
            "entry_price": 100.0,
            "current_price": 110.0,
            "quantity": 2
        }
    ]

    result = PaperPortfolioValuationEngine().calculate(positions)

    assert result["position_count"] == 1
    assert result["total_market_value"] == 220.0
    assert result["total_unrealized_pnl"] == 20.0
    assert result["positions"][0]["unrealized_pct"] == 10.0


def test_portfolio_valuation_calculates_multiple_positions():
    positions = [
        {
            "symbol": "NVDA",
            "entry_price": 100.0,
            "current_price": 110.0,
            "quantity": 2
        },
        {
            "symbol": "MSFT",
            "entry_price": 50.0,
            "current_price": 45.0,
            "quantity": 4
        }
    ]

    result = PaperPortfolioValuationEngine().calculate(positions)

    assert result["position_count"] == 2
    assert result["total_market_value"] == 400.0
    assert result["total_unrealized_pnl"] == 0.0


def test_portfolio_valuation_handles_empty_positions():
    result = PaperPortfolioValuationEngine().calculate([])

    assert result["position_count"] == 0
    assert result["total_market_value"] == 0.0
    assert result["total_unrealized_pnl"] == 0.0
