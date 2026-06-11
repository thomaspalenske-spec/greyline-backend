from datetime import datetime

from app.services.greyline_safety_gate_engine import GreyLineSafetyGateEngine


class GreyLineExecutionGateIntegrationEngine:

    def __init__(self):
        self.safety_gate = GreyLineSafetyGateEngine()

    def evaluate_and_route(self, allocations, execution_engine, broker_interface):

        live_enabled = self.safety_gate.status()["live_enabled"]

        # STEP 1 — SAFETY CHECK
        if not self.safety_gate.can_execute_live():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "EXECUTION_BLOCKED_BY_SAFETY_GATE",
                "reason": "LIVE_EXECUTION_NOT_ALLOWED",
                "executed_trades": [],
                "broker_results": [],
                "live_enabled": live_enabled
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
            "live_enabled": live_enabled
        }
