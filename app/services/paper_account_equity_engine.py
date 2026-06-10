from datetime import datetime

from app.services.paper_portfolio_valuation_engine import PaperPortfolioValuationEngine


class PaperAccountEquityEngine:

    def calculate(
        self,
        cash_balance,
        positions
    ):
        valuation = PaperPortfolioValuationEngine().calculate(
            positions
        )

        equity = (
            cash_balance
            + valuation["total_market_value"]
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cash_balance": round(cash_balance, 2),
            "market_value": valuation["total_market_value"],
            "unrealized_pnl": valuation["total_unrealized_pnl"],
            "equity": round(equity, 2),
            "position_count": valuation["position_count"],
            "portfolio": valuation,
            "status": "ACCOUNT_EQUITY_CALCULATED"
        }
