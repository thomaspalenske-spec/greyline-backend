from datetime import datetime


class PortfolioSnapshotModelEngine:

    def create_empty_snapshot(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "account_id": None,
            "cash_balance": 0.0,
            "buying_power": 0.0,
            "equity": 0.0,
            "positions": [],
            "open_orders": [],
            "source": "MODEL_ONLY",
            "broker_connected": False,
            "execution_enabled": False,
            "status": "PORTFOLIO_SNAPSHOT_MODEL_ACTIVE"
        }
