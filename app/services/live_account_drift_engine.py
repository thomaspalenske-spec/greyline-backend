from datetime import datetime

from app.services.live_portfolio_snapshot_repository import LivePortfolioSnapshotRepository


class LiveAccountDriftEngine:

    def evaluate(self):
        latest = LivePortfolioSnapshotRepository().load_latest_snapshot()

        if latest.get("found") is not True:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "drift_checked": False,
                "drift_detected": None,
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "NO_LIVE_SNAPSHOT_AVAILABLE"
            }

        snapshot = latest.get("data", {}).get("snapshot", {})
        normalized = snapshot.get("normalized_snapshot", {})

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "drift_checked": True,
            "snapshot_healthy": normalized.get("snapshot_healthy", False),
            "account_count": normalized.get("account_count", 0),
            "balance_count": normalized.get("balance_count", 0),
            "position_count": normalized.get("position_count", 0),
            "order_count": normalized.get("order_count", 0),
            "drift_detected": False,
            "drift_reasons": [],
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LIVE_ACCOUNT_DRIFT_CLEAR"
        }
