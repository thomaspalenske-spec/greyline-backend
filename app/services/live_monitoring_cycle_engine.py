from datetime import datetime

from app.services.live_portfolio_snapshot_persistence_service import LivePortfolioSnapshotPersistenceService
from app.services.live_broker_health_engine import LiveBrokerHealthEngine
from app.services.live_account_drift_engine import LiveAccountDriftEngine


class LiveMonitoringCycleEngine:

    def run_cycle(self):
        persistence_result = LivePortfolioSnapshotPersistenceService().save_and_verify_live_snapshot()
        broker_health = LiveBrokerHealthEngine().evaluate()
        account_drift = LiveAccountDriftEngine().evaluate()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "cycle_type": "TRADESTATION_LIVE_READ_ONLY_MONITORING",
            "snapshot_persistence": persistence_result,
            "broker_health": broker_health,
            "account_drift": account_drift,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LIVE_MONITORING_CYCLE_COMPLETE"
        }
