from datetime import datetime

from app.services.live_portfolio_snapshot_builder import LivePortfolioSnapshotBuilder
from app.services.live_portfolio_snapshot_repository import LivePortfolioSnapshotRepository


class LivePortfolioSnapshotPersistenceService:

    def save_and_verify_live_snapshot(self):
        snapshot = LivePortfolioSnapshotBuilder().build_snapshot()
        repo = LivePortfolioSnapshotRepository()

        save_result = repo.save_snapshot(snapshot)
        load_result = repo.load_latest_snapshot()

        verified = (
            save_result.get("saved") is True
            and load_result.get("found") is True
        )

        raw_snapshot = snapshot.get("raw_snapshot", {})
        normalized_snapshot = snapshot.get("normalized_snapshot", {})

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "snapshot_status": raw_snapshot.get("status"),
            "snapshot_healthy": normalized_snapshot.get("snapshot_healthy"),
            "snapshot_saved": save_result.get("saved"),
            "snapshot_loaded": load_result.get("found"),
            "snapshot_verified": verified,
            "execution_enabled": False,
            "status": "LIVE_PORTFOLIO_SNAPSHOT_PERSISTED" if verified else "LIVE_PORTFOLIO_SNAPSHOT_PERSISTENCE_FAILED"
        }
