from datetime import datetime


class SystemStatusEngine:

    def get_status(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "backend": "ONLINE",
            "ledger_engine": "ONLINE",
            "account_engine": "ONLINE",
            "snapshot_engine": "ONLINE",
            "reconciliation_engine": "ONLINE",
            "status": "OPERATIONAL"
        }
