import json
from datetime import datetime
from pathlib import Path


class LiveMonitoringEventLog:

    def __init__(self):
        self.log_dir = Path("app/data/live_monitoring")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "live_monitoring_events.jsonl"

    def record_event(self, cycle_result):
        broker_health = cycle_result.get("broker_health", {})
        account_drift = cycle_result.get("account_drift", {})

        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "cycle_status": cycle_result.get("status"),
            "health_score": broker_health.get("health_score"),
            "broker_status": broker_health.get("status"),
            "drift_detected": account_drift.get("drift_detected"),
            "drift_reasons": account_drift.get("drift_reasons", []),
            "account_count": broker_health.get("account_count"),
            "balance_count": broker_health.get("balance_count"),
            "position_count": broker_health.get("position_count"),
            "order_count": broker_health.get("order_count"),
            "execution_enabled": False,
            "order_placement_allowed": False
        }

        with self.log_file.open("a") as f:
            f.write(json.dumps(event) + "\n")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "event_logged": True,
            "log_file": str(self.log_file),
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LIVE_MONITORING_EVENT_LOGGED"
        }
