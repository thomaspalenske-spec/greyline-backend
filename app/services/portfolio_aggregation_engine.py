from datetime import datetime


class PortfolioAggregationEngine:

    def aggregate_empty_portfolio(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "account": {
                "account_id": None,
                "account_type": None,
                "broker": "TradeStation"
            },
            "balance": {
                "cash_balance": 0.0,
                "equity": 0.0,
                "buying_power": 0.0,
                "day_trading_buying_power": 0.0,
                "maintenance_margin": 0.0,
                "excess_liquidity": 0.0
            },
            "positions": [],
            "open_orders": [],
            "snapshots": [],
            "source": "MODEL_ONLY",
            "broker_connected": False,
            "execution_enabled": False,
            "status": "PORTFOLIO_AGGREGATION_ACTIVE"
        }
