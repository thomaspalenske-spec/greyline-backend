from datetime import datetime

from app.services.greyline_system_launch_controller_engine import GreyLineSystemLaunchControllerEngine


class GreyLineSystemRuntimeEngine:

    def __init__(self):

        self.controller = GreyLineSystemLaunchControllerEngine()

    def start(self):

        boot = self.controller.boot()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "SYSTEM_RUNTIME_STARTED",
            "boot": boot
        }

    def run(self, cycles=1):

        results = []

        for _ in range(cycles):

            results.append(self.controller.run_safe_cycle(10000))

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "RUNTIME_EXECUTION_COMPLETE",
            "cycle_count": cycles,
            "results": results
        }
