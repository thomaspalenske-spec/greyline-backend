from datetime import datetime

from app.services.greyline_safety_gate_engine import GreyLineSafetyGateEngine
from app.services.operator_event_bus_engine import OperatorEventBusEngine
from app.services.reliability_governor_engine import ReliabilityGovernorEngine


class GreyLineExecutionGateIntegrationEngine:

    def __init__(self):
        self.safety_gate = GreyLineSafetyGateEngine()

    def evaluate_and_route(self, allocations, execution_engine, broker_interface):

        live_enabled = self.safety_gate.status()["live_enabled"]
        reliability_governor = ReliabilityGovernorEngine().evaluate()

        # STEP 1 — RELIABILITY GOVERNOR CHECK

        if reliability_governor.get("execution_allowed") is not True:
            OperatorEventBusEngine().publish(
                source="GreyLineExecutionGateIntegrationEngine",
                category="EXECUTION_GATE",
                severity="CRITICAL",
                title="Execution Blocked by Reliability Governor",
                message="Reliability governor denied execution.",
                symbol=None,
                trade_id=None,
                ack_required=True,
                payload=reliability_governor,
            )
        if reliability_governor.get("execution_allowed") is not True:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "EXECUTION_BLOCKED_BY_RELIABILITY_GOVERNOR",
                "reason": reliability_governor.get("reason"),
                "executed_trades": [],
                "broker_results": [],
                "live_enabled": live_enabled,
                "reliability_governor": reliability_governor,
            }

        # STEP 2 — SAFETY CHECK
        if not self.safety_gate.can_execute_live():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "EXECUTION_BLOCKED_BY_SAFETY_GATE",
                "reason": "LIVE_EXECUTION_NOT_ALLOWED",
                "executed_trades": [],
                "broker_results": [],
                "live_enabled": live_enabled,
                "reliability_governor": reliability_governor
            }

        # STEP 2 — EXECUTE THROUGH ENGINE
        execution_result = execution_engine.execute(
            allocations,
            current_positions=[]
        )

        # STEP 3 — ROUTE TO BROKER
        broker_results = []

        for trade in execution_result.get("executed_trades", []):

            broker_response = broker_interface.submit_order(
                symbol=trade["symbol"],
                quantity=trade["quantity"],
                side="BUY",
                price=trade["fill_price"]
            )

            broker_results.append({
                "trade": trade,
                "broker_response": broker_response
            })

        # STEP 4 — RETURN SUCCESS PATH (ALWAYS SAME SCHEMA)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "EXECUTION_GATE_PASS_COMPLETE",
            "execution": execution_result,
            "broker_results": broker_results,
            "live_enabled": live_enabled,
            "reliability_governor": reliability_governor
        }
