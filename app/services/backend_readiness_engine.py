from datetime import datetime


class BackendReadinessEngine:

    def evaluate_readiness(
        self,
        api_online,
        ledger_online,
        snapshot_online,
        reconciliation_online,
        account_health
    ):

        ready = (
            api_online
            and ledger_online
            and snapshot_online
            and reconciliation_online
            and account_health == "HEALTHY"
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "api_online": api_online,
            "ledger_online": ledger_online,
            "snapshot_online": snapshot_online,
            "reconciliation_online": reconciliation_online,
            "account_health": account_health,
            "backend_ready": ready
        }
