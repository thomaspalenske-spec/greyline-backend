from datetime import datetime

from app.services.greyline_event_stream_engine import GreyLineEventStreamEngine
from app.services.greyline_event_processor_engine import GreyLineEventProcessorEngine
from app.services.greyline_strategy_regime_engine import GreyLineStrategyRegimeEngine
from app.services.greyline_strategy_execution_router_engine import GreyLineStrategyExecutionRouterEngine
from app.services.greyline_portfolio_allocation_engine import GreyLinePortfolioAllocationEngine
from app.services.greyline_execution_simulation_engine import GreyLineExecutionSimulationEngine
from app.services.greyline_ledger_feedback_loop_engine import GreyLineLedgerFeedbackLoopEngine


class GreyLineUnifiedDecisionOrchestratorEngine:

    def run_cycle(self, starting_capital=10000):

        stream = GreyLineEventStreamEngine()
        processor = GreyLineEventProcessorEngine()
        regime_engine = GreyLineStrategyRegimeEngine()
        router = GreyLineStrategyExecutionRouterEngine()
        allocator = GreyLinePortfolioAllocationEngine()
        executor = GreyLineExecutionSimulationEngine()
        feedback = GreyLineLedgerFeedbackLoopEngine()

        events = stream.generate_batch(5)["events"]

        positions = [
            {"symbol": "NVDA", "entry_price": 100, "quantity": 10}
        ]

        processed = processor.process_events(events, positions)

        regime = regime_engine.detect_regime(processed)

        routing = router.route(regime)

        allocations = allocator.allocate(
            {"signals": [{"symbol": "NVDA", "signal": "HOLD_WINNER", "change_pct": regime.get("avg_change_pct", 0)}]},
            starting_capital
        )

        execution = executor.execute(allocations, positions)

        ledger = feedback.apply(execution, None)

        return {
            "timestamp": datetime.utcnow().isoformat(),

            "regime": regime,
            "routing": routing,

            "allocations": allocations,
            "execution": execution,
            "ledger": ledger,

            "status": "UNIFIED_DECISION_CYCLE_COMPLETE"
        }
