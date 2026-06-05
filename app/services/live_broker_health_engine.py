from datetime import datetime

from app.services.live_portfolio_snapshot_builder import LivePortfolioSnapshotBuilder


class LiveBrokerHealthEngine:

    def evaluate(self):
        snapshot = LivePortfolioSnapshotBuilder().build_snapshot()
        raw = snapshot.get("raw_snapshot", {})
        normalized = snapshot.get("normalized_snapshot", {})

        accounts_available = raw.get("accounts", {}).get("http_status") == 200
        balances_available = raw.get("balances", {}).get("final_result", {}).get("http_status") == 200
        positions_available = raw.get("positions", {}).get("final_result", {}).get("http_status") == 200
        orders_available = raw.get("orders", {}).get("http_status") == 200

        health_score = 0
        health_score += 25 if accounts_available else 0
        health_score += 25 if balances_available else 0
        health_score += 25 if positions_available else 0
        health_score += 25 if orders_available else 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "broker_connected": health_score > 0,
            "accounts_available": accounts_available,
            "balances_available": balances_available,
            "positions_available": positions_available,
            "orders_available": orders_available,
            "snapshot_healthy": normalized.get("snapshot_healthy", False),
            "account_count": normalized.get("account_count", 0),
            "balance_count": normalized.get("balance_count", 0),
            "position_count": normalized.get("position_count", 0),
            "order_count": normalized.get("order_count", 0),
            "health_score": health_score,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LIVE_BROKER_HEALTHY" if health_score == 100 else "LIVE_BROKER_DEGRADED"
        }
