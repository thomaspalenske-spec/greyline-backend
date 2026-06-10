from datetime import datetime
import time

from app.services.greyline_system_control_loop_engine import (
    GreyLineSystemControlLoopEngine
)


class GreyLineControlLoopSchedulerEngine:

    def __init__(self, interval_seconds=5):
        self.interval_seconds = interval_seconds
        self.running = False
        self.cycles = 0

    def start(self, max_cycles=3):

        self.running = True

        results = []

        while self.running and self.cycles < max_cycles:

            cycle_result = (
                GreyLineSystemControlLoopEngine()
                .run_cycle()
            )

            self.cycles += 1

            results.append(cycle_result)

            time.sleep(self.interval_seconds)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cycles_run": self.cycles,
            "max_cycles": max_cycles,
            "results": results,
            "status": "CONTROL_LOOP_SCHEDULER_COMPLETE"
        }
