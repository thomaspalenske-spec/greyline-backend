from datetime import datetime

from app.services.live_monitoring_cycle_engine import LiveMonitoringCycleEngine


class LiveMonitoringSchedulerEngine:

    def run_once(self):
        cycle_result = LiveMonitoringCycleEngine().run_cycle()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "scheduler_mode": "MANUAL_RUN_ONCE",
            "cycle_result": cycle_result,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LIVE_MONITORING_SCHEDULER_RUN_COMPLETE"
        }
