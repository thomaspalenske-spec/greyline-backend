from datetime import datetime

from app.services.tradestation_account_discovery_live_engine import TradeStationAccountDiscoveryLiveEngine
from app.services.tradestation_balance_retry_service import TradeStationBalanceRetryService
from app.services.tradestation_positions_retry_service import TradeStationPositionsRetryService
from app.services.tradestation_orders_live_engine import TradeStationOrdersLiveEngine
from app.services.live_portfolio_snapshot_normalizer import LivePortfolioSnapshotNormalizer


class LivePortfolioSnapshotBuilder:

    def build_snapshot(self):
        accounts = TradeStationAccountDiscoveryLiveEngine().discover_accounts()
        balances = TradeStationBalanceRetryService().get_balance_with_refresh_retry()
        positions = TradeStationPositionsRetryService().get_positions_with_refresh_retry()
        orders = TradeStationOrdersLiveEngine().get_orders()

        healthy = (
            accounts.get("http_status") == 200
            and balances.get("final_result", {}).get("http_status") == 200
            and positions.get("final_result", {}).get("http_status") == 200
            and orders.get("http_status") == 200
        )

        raw_snapshot = {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "accounts": accounts,
            "balances": balances,
            "positions": positions,
            "orders": orders,
            "execution_enabled": False,
            "snapshot_healthy": healthy,
            "status": "LIVE_PORTFOLIO_SNAPSHOT_READY" if healthy else "LIVE_PORTFOLIO_SNAPSHOT_DEGRADED"
        }

        normalized_snapshot = LivePortfolioSnapshotNormalizer().normalize(raw_snapshot)

        return {
            "raw_snapshot": raw_snapshot,
            "normalized_snapshot": normalized_snapshot,
            "execution_enabled": False
        }
