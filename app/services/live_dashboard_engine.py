from datetime import datetime

from app.services.live_broker_health_engine import LiveBrokerHealthEngine
from app.services.live_broker_summary_engine import LiveBrokerSummaryEngine
from app.services.live_positions_ledger_engine import LivePositionsLedgerEngine
from app.services.live_orders_ledger_engine import LiveOrdersLedgerEngine


class LiveDashboardEngine:

    def get_dashboard(self):
        broker_health = LiveBrokerHealthEngine().evaluate()
        account_summary = LiveBrokerSummaryEngine().summarize()
        positions_ledger = LivePositionsLedgerEngine().get_positions_ledger()
        orders_ledger = LiveOrdersLedgerEngine().get_orders_ledger()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "TRADESTATION_LIVE_READ_ONLY",
            "broker_health": broker_health,
            "account_summary": account_summary,
            "positions": positions_ledger,
            "orders": orders_ledger,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LIVE_DASHBOARD_READY"
        }
