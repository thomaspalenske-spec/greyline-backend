from datetime import datetime

from app.services.live_portfolio_snapshot_builder import LivePortfolioSnapshotBuilder


class LiveOrdersLedgerEngine:

    def get_orders_ledger(self):
        snapshot = LivePortfolioSnapshotBuilder().build_snapshot()
        normalized = snapshot.get("normalized_snapshot", {})
        orders = normalized.get("orders", [])

        ledger_orders = []

        for order in orders:
            ledger_orders.append({
                "source": "TRADESTATION_LIVE_READ_ONLY",
                "broker": "TradeStation",
                "account_id": order.get("AccountID"),
                "order_id": order.get("OrderID"),
                "symbol": order.get("Symbol"),
                "order_type": order.get("OrderType"),
                "quantity": order.get("Quantity"),
                "limit_price": order.get("LimitPrice"),
                "stop_price": order.get("StopPrice"),
                "status": order.get("Status"),
                "entered_time": order.get("OpenedDateTime") or order.get("EnteredDateTime"),
                "execution_enabled": False,
                "status_normalized": "LIVE_ORDER_LEDGER_ADAPTED"
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "TRADESTATION_LIVE_READ_ONLY",
            "snapshot_healthy": normalized.get("snapshot_healthy", False),
            "open_order_count": len(ledger_orders),
            "orders": ledger_orders,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LIVE_ORDERS_LEDGER_READY"
        }
