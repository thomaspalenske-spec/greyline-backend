from datetime import datetime


class LivePortfolioSnapshotNormalizer:

    def normalize(self, snapshot):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "snapshot_healthy": snapshot.get("snapshot_healthy", False),
            "account_count": len(
                snapshot.get("accounts", {})
                .get("response_preview", "")
            ),
            "positions_present": (
                snapshot.get("positions", {})
                .get("final_result", {})
                .get("http_status") == 200
            ),
            "orders_present": (
                snapshot.get("orders", {})
                .get("http_status") == 200
            ),
            "execution_enabled": False,
            "status": "NORMALIZED_LIVE_PORTFOLIO_READY"
        }
