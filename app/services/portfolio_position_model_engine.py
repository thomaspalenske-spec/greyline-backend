from datetime import datetime


class PortfolioPositionModelEngine:

    def create_empty_position(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": None,
            "asset_type": None,
            "quantity": 0.0,
            "average_cost": 0.0,
            "market_value": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "source": "MODEL_ONLY",
            "broker_connected": False,
            "execution_enabled": False,
            "status": "PORTFOLIO_POSITION_MODEL_ACTIVE"
        }
