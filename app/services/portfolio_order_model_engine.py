from datetime import datetime


class PortfolioOrderModelEngine:

    def create_empty_order(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "order_id": None,
            "symbol": None,
            "asset_type": None,
            "order_type": None,
            "side": None,
            "quantity": 0.0,
            "limit_price": None,
            "stop_price": None,
            "status": "MODEL_ONLY",
            "created_at": None,
            "filled_at": None,
            "broker_connected": False,
            "execution_enabled": False,
            "source": "MODEL_ONLY",
            "model_status": "PORTFOLIO_ORDER_MODEL_ACTIVE"
        }
