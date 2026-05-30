from datetime import datetime


class AccountHealthEngine:

    def evaluate_health(
        self,
        reconciliation_status,
        drift_detected,
        snapshot_valid
    ):

        status = "HEALTHY"

        if reconciliation_status != "PASS":
            status = "RECONCILIATION_FAILURE"

        if drift_detected:
            status = "ACCOUNT_DRIFT_DETECTED"

        if not snapshot_valid:
            status = "SNAPSHOT_FAILURE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "reconciliation_status": reconciliation_status,
            "drift_detected": drift_detected,
            "snapshot_valid": snapshot_valid,
            "account_health": status
        }
