from datetime import datetime


class PortfolioAccountModelEngine:

    def create_empty_account(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "account_id": None,
            "account_type": None,
            "broker": "TradeStation",
            "balance": {
                "cash_balance": 0.0,
                "equity": 0.0,
                "buying_power": 0.0
            },
            "positions": [],
            "open_orders": [],
            "snapshots": [],
            "source": "MODEL_ONLY",
            "broker_connected": False,
            "execution_enabled": False,
            "status": "PORTFOLIO_ACCOUNT_MODEL_ACTIVE"
        }
