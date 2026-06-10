from datetime import datetime

from app.services.greyline_system_control_loop_engine import GreyLineSystemControlLoopEngine
from app.services.greyline_event_stream_engine import GreyLineEventStreamEngine
from app.services.greyline_event_processor_engine import GreyLineEventProcessorEngine


class GreyLineBacktestOrchestrationEngine:

    def run(self, cycles=5, starting_equity=10000):

        equity = starting_equity
        equity_curve = []

        stream = GreyLineEventStreamEngine()
        processor = GreyLineEventProcessorEngine()
        control = GreyLineSystemControlLoopEngine()

        for i in range(cycles):

            system_state = control.run_cycle()

            events = stream.generate_batch(5)["events"]

            positions = [
                {
                    "symbol": "NVDA",
                    "entry_price": 100,
                    "quantity": 10
                }
            ]

            result = processor.process_events(events, positions)

            equity += result.get("total_unrealized_pnl", 0)

            equity_curve.append({
                "cycle": i,
                "equity": round(equity, 2),
                "pnl": result.get("total_unrealized_pnl"),
                "system_ok": system_state.get("system_operational"),
                "timestamp": datetime.utcnow().isoformat()
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "starting_equity": starting_equity,
            "final_equity": round(equity, 2),
            "cycles": cycles,
            "equity_curve": equity_curve,
            "status": "BACKTEST_ORCHESTRATION_COMPLETE"
        }
