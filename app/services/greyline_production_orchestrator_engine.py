from datetime import datetime

from app.services.greyline_safety_gate_engine import GreyLineSafetyGateEngine
from app.services.greyline_live_mode_authorization_engine import GreyLineLiveModeAuthorizationEngine
from app.services.greyline_unified_decision_orchestrator_engine import GreyLineUnifiedDecisionOrchestratorEngine
from app.services.greyline_broker_interface_engine import GreyLineBrokerInterfaceEngine
from app.services.greyline_execution_gate_integration_engine import GreyLineExecutionGateIntegrationEngine


class GreyLineProductionOrchestratorEngine:

    def __init__(self):

        self.safety_gate = GreyLineSafetyGateEngine()
        self.live_auth = GreyLineLiveModeAuthorizationEngine(self.safety_gate)

        self.unified_engine = GreyLineUnifiedDecisionOrchestratorEngine()
        self.execution_gate = GreyLineExecutionGateIntegrationEngine()

        self.broker = GreyLineBrokerInterfaceEngine(mode="SIMULATION")

        self.mode = "SIMULATION"

    def set_mode(self, mode):

        if mode not in ["SIMULATION", "PAPER", "LIVE"]:
            return {
                "status": "INVALID_MODE",
                "mode": self.mode
            }

        if mode == "LIVE" and not self.safety_gate.live_enabled:
            return {
                "status": "LIVE_NOT_ENABLED",
                "mode": self.mode
            }

        self.mode = mode

        if mode == "LIVE":
            self.broker = GreyLineBrokerInterfaceEngine(mode="LIVE")

        return {
            "status": "MODE_SET",
            "mode": self.mode,
            "timestamp": datetime.utcnow().isoformat()
        }

    def run_cycle(self, capital=10000):

        result = self.unified_engine.run_cycle(capital)

        execution_result = self.execution_gate.evaluate_and_route(
            result["allocations"],
            result["execution"]["__class__"] if False else None,
            self.broker
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "mode": self.mode,

            "decision_cycle": result,
            "execution": execution_result,

            "status": "PRODUCTION_CYCLE_COMPLETE"
        }

    def status(self):

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "mode": self.mode,

            "safety_gate": self.safety_gate.status(),
            "live_authorization": self.live_auth.status(),

            "status": "PRODUCTION_ORCHESTRATOR_ACTIVE"
        }
