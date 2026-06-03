from datetime import datetime


class PortfolioDataModelEngine:

    def get_schema(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "portfolio": {
                "account_id": None,
                "cash_balance": 0.0,
                "buying_power": 0.0,
                "equity": 0.0,
                "positions": [],
                "open_orders": [],
                "snapshots": []
            },
            "execution_enabled": False,
            "status": "PORTFOLIO_SCHEMA_ACTIVE"
        }
