from datetime import datetime


class PortfolioBalanceModelEngine:

    def create_empty_balance(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "account_id": None,
            "cash_balance": 0.0,
            "equity": 0.0,
            "buying_power": 0.0,
            "day_trading_buying_power": 0.0,
            "maintenance_margin": 0.0,
            "excess_liquidity": 0.0,
            "source": "MODEL_ONLY",
            "broker_connected": False,
            "execution_enabled": False,
            "status": "PORTFOLIO_BALANCE_MODEL_ACTIVE"
        }
