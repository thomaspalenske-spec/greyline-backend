from app.services.greyline_system_runtime_engine import GreyLineSystemRuntimeEngine


class GreyLineDeploymentRuntimeEngine:

    def __init__(self):

        self.runtime = GreyLineSystemRuntimeEngine()

    def start_system(self):

        boot = self.runtime.start()

        return {
            "status": "GREYLINE_DEPLOYED",
            "boot": boot
        }

    def run_live(self, cycles=1):

        return self.runtime.run(cycles=cycles)

    def run_forever(self):

        # Production loop (simplified)
        while True:

            result = self.runtime.run(cycles=1)

            print(result)
