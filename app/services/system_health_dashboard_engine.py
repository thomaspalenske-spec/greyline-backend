from datetime import datetime

from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine
from app.services.background_scheduler_service import BackgroundSchedulerService
from app.services.learning_analytics_engine import LearningAnalyticsEngine
from app.services.adaptive_weight_governance_engine import AdaptiveWeightGovernanceEngine
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine
from app.services.ttl_cache import ttl_cached


class SystemHealthDashboardEngine:

    @ttl_cached(30, env_key="GREYLINE_SHADOW_CACHE_TTL")
    def status(self):
        broker = TradeStationTokenMaintenanceEngine().evaluate()
        scheduler = BackgroundSchedulerService.status()
        learning = LearningAnalyticsEngine().summarize()
        governance = AdaptiveWeightGovernanceEngine().active_governance()

        broker_healthy = broker.get("status") == "TRADESTATION_TOKEN_MAINTENANCE_READY"
        scheduler_healthy = scheduler.get("thread_alive") is True or scheduler.get("last_status") == "BACKGROUND_SCHEDULER_CYCLE_COMPLETE"
        learning_healthy = learning.get("status") == "LEARNING_ANALYTICS_READY"
        governance_healthy = governance.get("status") == "ACTIVE_WEIGHT_GOVERNANCE_READY"

        overall = all([
            broker_healthy,
            scheduler_healthy,
            learning_healthy,
            governance_healthy
        ])

        ImmutableAuditLedgerEngine().record(
            "SYSTEM_HEALTH_CHECK",
            {
                "overall_health": "HEALTHY" if overall else "DEGRADED",
                "broker_healthy": broker_healthy,
                "scheduler_healthy": scheduler_healthy,
                "learning_healthy": learning_healthy,
                "governance_healthy": governance_healthy,
            },
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "SYSTEM_HEALTH_DASHBOARD",

            "overall_health": "HEALTHY" if overall else "DEGRADED",

            "broker": {
                "healthy": broker_healthy,
                "details": broker
            },

            "scheduler": {
                "healthy": scheduler_healthy,
                "details": scheduler
            },

            "learning": {
                "healthy": learning_healthy,
                "details": {
                    "total_learning_events":
                        learning.get("total_learning_events"),
                    "system_confidence_trend":
                        learning.get("system_confidence_trend")
                }
            },

            "governance": {
                "healthy": governance_healthy,
                "details": {
                    "approved_weight_changes":
                        governance.get("approved_weight_changes")
                }
            },

            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "SYSTEM_HEALTH_READY"
        }
