from datetime import datetime


class TradeStationLedgerAdapter:

    def adapt(self, normalized_snapshot):
        balances = normalized_snapshot.get("balances", [])
        positions = normalized_snapshot.get("positions", [])
        orders = normalized_snapshot.get("orders", [])

        primary_balance = balances[0] if balances else {}

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "TRADESTATION_LIVE_READ_ONLY",
            "broker": "TradeStation",
            "account_id": primary_balance.get("AccountID"),
            "account_type": primary_balance.get("AccountType"),
            "cash_balance": float(primary_balance.get("CashBalance", 0) or 0),
            "equity": float(primary_balance.get("Equity", 0) or 0),
            "buying_power": float(primary_balance.get("BuyingPower", 0) or 0),
            "market_value": float(primary_balance.get("MarketValue", 0) or 0),
            "todays_profit_loss": float(primary_balance.get("TodaysProfitLoss", 0) or 0),
            "positions": positions,
            "open_orders": orders,
            "position_count": len(positions),
            "open_order_count": len(orders),
            "execution_enabled": False,
            "status": "TRADESTATION_LEDGER_ADAPTED"
        }
