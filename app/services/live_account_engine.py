from datetime import datetime

from app.services.live_portfolio_snapshot_builder import LivePortfolioSnapshotBuilder
from app.services.tradestation_ledger_adapter import TradeStationLedgerAdapter


class LiveAccountEngine:

    def get_account(self):
        snapshot = LivePortfolioSnapshotBuilder().build_snapshot()
        normalized_snapshot = snapshot.get("normalized_snapshot", {})

        ledger_account = TradeStationLedgerAdapter().adapt(normalized_snapshot)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "TRADESTATION_LIVE_READ_ONLY",
            "snapshot_healthy": normalized_snapshot.get("snapshot_healthy", False),
            "account": ledger_account,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LIVE_ACCOUNT_READY" if normalized_snapshot.get("snapshot_healthy") else "LIVE_ACCOUNT_DEGRADED"
        }
