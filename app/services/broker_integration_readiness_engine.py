from datetime import datetime


class BrokerIntegrationReadinessEngine:

    def evaluate_readiness(
        self,
        ledger_supremacy_active,
        audit_log_active,
        snapshot_restore_active,
        reconciliation_active,
        drift_detection_active,
        autonomous_execution_enabled
    ):

        safe_for_broker_prep = (
            ledger_supremacy_active
            and audit_log_active
            and snapshot_restore_active
            and reconciliation_active
            and drift_detection_active
            and not autonomous_execution_enabled
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "ledger_supremacy_active": ledger_supremacy_active,
            "audit_log_active": audit_log_active,
            "snapshot_restore_active": snapshot_restore_active,
            "reconciliation_active": reconciliation_active,
            "drift_detection_active": drift_detection_active,
            "autonomous_execution_enabled": autonomous_execution_enabled,
            "safe_for_broker_prep": safe_for_broker_prep,
            "allowed_authority_level": "OBSERVE_RECOMMEND_ONLY"
        }
