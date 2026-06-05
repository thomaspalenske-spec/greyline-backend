from datetime import datetime

from app.services.live_account_engine import LiveAccountEngine


class LiveBrokerSummaryEngine:

    def summarize(self):
        live_account = LiveAccountEngine().get_account()
        account = live_account.get("account", {})

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": account.get("broker"),
            "account_id": account.get("account_id"),
            "account_type": account.get("account_type"),
            "equity": account.get("equity"),
            "cash_balance": account.get("cash_balance"),
            "buying_power": account.get("buying_power"),
            "market_value": account.get("market_value"),
            "todays_profit_loss": account.get("todays_profit_loss"),
            "position_count": account.get("position_count"),
            "open_order_count": account.get("open_order_count"),
            "snapshot_healthy": live_account.get("snapshot_healthy"),
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": live_account.get("status")
        }
