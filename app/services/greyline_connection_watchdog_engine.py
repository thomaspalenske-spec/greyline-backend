from datetime import datetime
from os import getenv

from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine
from app.services.tradestation_account_discovery_live_engine import TradeStationAccountDiscoveryLiveEngine
from app.services.live_broker_summary_engine import LiveBrokerSummaryEngine
from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
from app.services.tradestation_orders_live_engine import TradeStationOrdersLiveEngine
from app.services.background_scheduler_service import BackgroundSchedulerService
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class GreyLineConnectionWatchdogEngine:
    def run(self):
        token = TradeStationTokenMaintenanceEngine().evaluate()
        accounts = TradeStationAccountDiscoveryLiveEngine().discover_accounts()
        summary = LiveBrokerSummaryEngine().summarize()
        positions = TradeStationPositionsLiveEngine().get_positions()
        orders = TradeStationOrdersLiveEngine().get_orders()
        scheduler = BackgroundSchedulerService.status()

        # Expected account comes from config, not a hardcoded id. Fail-safe: if it
        # is not configured, account_ok is False and the watchdog reports degraded.
        expected_account_id = getenv("TRADESTATION_MARGIN_ACCOUNT_ID") or getenv("TS_MARGIN_ACCOUNT_ID")
        account_ok = bool(expected_account_id) and summary.get("account_id") == expected_account_id
        summary_ok = summary.get("status") == "LIVE_ACCOUNT_READY"
        scheduler_ok = scheduler.get("scheduler_enabled") is True and scheduler.get("thread_alive") is True

        if not scheduler_ok:
            BackgroundSchedulerService.start()

            ImmutableAuditLedgerEngine().record(
                "WATCHDOG_SCHEDULER_AUTO_RESTART",
                {
                    "scheduler_enabled": True,
                    "execution_enabled": False,
                    "order_placement_allowed": False,
                },
            )

            scheduler = BackgroundSchedulerService.status()
            scheduler_ok = scheduler.get("scheduler_enabled") is True and scheduler.get("thread_alive") is True

        overall_ready = account_ok and summary_ok and scheduler_ok

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "GREYLINE_CONNECTION_WATCHDOG",
            "token_status": token.get("status"),
            "account_discovery_status": accounts.get("status"),
            "live_account_status": summary.get("status"),
            "default_account_id": summary.get("account_id"),
            "default_account_ok": account_ok,
            "snapshot_healthy": summary.get("snapshot_healthy"),
            "position_count": summary.get("position_count"),
            "open_order_count": summary.get("open_order_count"),
            "positions_status": positions.get("status"),
            "orders_status": orders.get("status"),
            "scheduler_enabled": scheduler.get("scheduler_enabled"),
            "scheduler_thread_alive": scheduler.get("thread_alive"),
            "execution_enabled": False,
            "order_placement_allowed": False,
            "overall_ready": overall_ready,
            "status": "GREYLINE_CONNECTION_READY" if overall_ready else "GREYLINE_CONNECTION_DEGRADED",
        }

        ImmutableAuditLedgerEngine().record("GREYLINE_CONNECTION_WATCHDOG", result)
        return result
