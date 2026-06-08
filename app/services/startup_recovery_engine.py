from datetime import datetime
from pathlib import Path

from app.services.system_health_dashboard_engine import SystemHealthDashboardEngine
from app.services.master_decision_history_engine import MasterDecisionHistoryEngine
from app.services.decision_learning_memory_engine import DecisionLearningMemoryEngine
from app.services.adaptive_weight_governance_engine import AdaptiveWeightGovernanceEngine
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class StartupRecoveryEngine:

    def readiness(self):
        health = SystemHealthDashboardEngine().status()
        decision_history = MasterDecisionHistoryEngine().get_history(limit=5)
        learning_memory = DecisionLearningMemoryEngine().get_history(limit=5)
        governance = AdaptiveWeightGovernanceEngine().active_governance(limit=5)

        required_paths = {
            "master_decision_history": Path("app/data/master_decisions/master_decision_events.jsonl"),
            "learning_history": Path("app/data/learning/decision_learning_history.jsonl"),
            "adaptive_governance_dir": Path("app/data/adaptive_governance"),
        }

        path_status = {
            name: path.exists()
            for name, path in required_paths.items()
        }

        broker_ready = health.get("broker", {}).get("healthy") is True
        scheduler_ready = health.get("scheduler", {}).get("healthy") is True
        learning_ready = learning_memory.get("status") in [
            "DECISION_LEARNING_HISTORY_READY",
            "NO_DECISION_LEARNING_HISTORY_FOUND",
        ]
        governance_ready = governance.get("status") == "ACTIVE_WEIGHT_GOVERNANCE_READY"
        decision_history_ready = decision_history.get("status") in [
            "MASTER_DECISION_HISTORY_READY",
            "NO_MASTER_DECISION_HISTORY_FOUND",
        ]

        filesystem_ready = all(path_status.values())

        overall_ready = all([
            broker_ready,
            scheduler_ready,
            learning_ready,
            governance_ready,
            decision_history_ready,
            filesystem_ready,
        ])

        ImmutableAuditLedgerEngine().record(
            "STARTUP_READINESS_CHECK",
            {
                "startup_ready": overall_ready,
                "broker_ready": broker_ready,
                "scheduler_ready": scheduler_ready,
                "decision_history_ready": decision_history_ready,
                "learning_memory_ready": learning_ready,
                "governance_ready": governance_ready,
                "filesystem_ready": filesystem_ready,
                "system_health_status": health.get("overall_health"),
            },
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "STARTUP_RECOVERY",
            "startup_ready": overall_ready,
            "broker_ready": broker_ready,
            "scheduler_ready": scheduler_ready,
            "decision_history_ready": decision_history_ready,
            "learning_memory_ready": learning_ready,
            "governance_ready": governance_ready,
            "filesystem_ready": filesystem_ready,
            "path_status": path_status,
            "system_health_status": health.get("overall_health"),
            "decision_events_available": decision_history.get("event_count", 0),
            "learning_events_available": learning_memory.get("event_count", 0),
            "approved_weight_changes": governance.get("approved_weight_changes", 0),
            "automatic_background_execution": False,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "STARTUP_READY" if overall_ready else "STARTUP_DEGRADED",
        }
