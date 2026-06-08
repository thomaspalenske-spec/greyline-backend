from datetime import datetime

from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine
from app.services.decision_scheduler_engine import DecisionSchedulerEngine
from app.services.learning_analytics_engine import LearningAnalyticsEngine
from app.services.adaptive_weight_governance_engine import AdaptiveWeightGovernanceEngine


class SystemHealthDashboardEngine:

    def status(self):
        broker = TradeStationTokenMaintenanceEngine().evaluate()
        scheduler = DecisionSchedulerEngine().status()
        learning = LearningAnalyticsEngine().summarize()
        governance = AdaptiveWeightGovernanceEngine().active_governance()

        broker_healthy = broker.get("status") == "TRADESTATION_TOKEN_MAINTENANCE_READY"
        scheduler_healthy = scheduler.get("status") == "DECISION_SCHEDULER_READY"
        learning_healthy = learning.get("status") == "LEARNING_ANALYTICS_READY"
        governance_healthy = governance.get("status") == "ACTIVE_WEIGHT_GOVERNANCE_READY"

        overall = all([
            broker_healthy,
            scheduler_healthy,
            learning_healthy,
            governance_healthy
        ])

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
