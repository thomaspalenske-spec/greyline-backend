from datetime import datetime

from app.services.greyline_deployment_state_engine import GreyLineDeploymentStateEngine
from app.services.greyline_safety_gate_engine import GreyLineSafetyGateEngine
from app.services.greyline_live_mode_authorization_engine import GreyLineLiveModeAuthorizationEngine
from app.services.greyline_production_orchestrator_engine import GreyLineProductionOrchestratorEngine


class GreyLineSystemLaunchControllerEngine:

    def __init__(self):

        self.state = GreyLineDeploymentStateEngine()
        self.safety = GreyLineSafetyGateEngine()
        self.auth = GreyLineLiveModeAuthorizationEngine(self.safety)
        self.orchestrator = GreyLineProductionOrchestratorEngine()

    def boot(self):

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "SYSTEM_BOOT_COMPLETE",
            "deployment_state": self.state.status(),
            "safety_state": self.safety.status(),
            "live_authorization": self.auth.status(),
            "orchestrator_state": self.orchestrator.status()
        }

    def run_safe_cycle(self, capital=10000):

        # MUST BE IN PAPER OR SIM MODE
        if self.state.state not in ["SIMULATION", "PAPER"]:

            return {
                "status": "BLOCKED_UNSAFE_DEPLOYMENT_STATE",
                "state": self.state.state
            }

        result = self.orchestrator.run_cycle(capital)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "SAFE_CYCLE_COMPLETE",
            "state": self.state.state,
            "result": result
        }

    def run_live_cycle(self, capital=10000):

        # HARD GATE CHECKS
        if self.state.state != "LIVE_EXECUTION":

            return {
                "status": "BLOCKED_NOT_IN_LIVE_EXECUTION_STATE",
                "state": self.state.state
            }

        if not self.safety.can_execute_live():

            return {
                "status": "BLOCKED_SAFETY_GATE",
                "live_enabled": False
            }

        result = self.orchestrator.run_cycle(capital)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "LIVE_CYCLE_EXECUTED",
            "result": result
        }
