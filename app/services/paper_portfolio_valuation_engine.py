from datetime import datetime

from app.services.paper_pnl_engine import PaperPnLEngine


class PaperPortfolioValuationEngine:

    def calculate(self, positions):
        total_market_value = 0.0
        total_unrealized_pnl = 0.0

        evaluated_positions = []

        for position in positions:

            pnl = PaperPnLEngine().calculate(
                entry_price=position["entry_price"],
                current_price=position["current_price"],
                quantity=position["quantity"]
            )

            market_value = (
                position["current_price"]
                * position["quantity"]
            )

            total_market_value += market_value
            total_unrealized_pnl += pnl["unrealized_pnl"]

            evaluated_positions.append(
                {
                    **position,
                    "market_value": round(market_value, 2),
                    "unrealized_pnl": pnl["unrealized_pnl"],
                    "unrealized_pct": pnl["unrealized_pct"]
                }
            )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "position_count": len(evaluated_positions),
            "total_market_value": round(total_market_value, 2),
            "total_unrealized_pnl": round(total_unrealized_pnl, 2),
            "positions": evaluated_positions,
            "status": "PORTFOLIO_VALUATION_COMPLETE"
        }
