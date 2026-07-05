from datetime import datetime
import copy

from app.services.simulation.simulation_clock import SimulationClock
from app.services.simulation.simulation_ledger_engine import SimulationLedgerEngine
from app.services.simulation.simulation_learning_engine import SimulationLearningEngine
from app.services.simulation.simulation_outcome_reveal_engine import SimulationOutcomeRevealEngine
from app.services.simulation.simulation_outcome_ledger_engine import SimulationOutcomeLedgerEngine
from app.services.simulation.simulation_execution_engine import SimulationExecutionEngine
from app.services.simulation.simulation_position_engine import SimulationPositionEngine
from app.services.simulation.simulation_exit_engine import SimulationExitEngine
from app.services.simulation.market_replay_engine import MarketReplayEngine
from app.services.simulation.greyline_simulation_decision_adapter import GreyLineSimulationDecisionAdapter
from app.services.simulation.historical_component_builder import HistoricalComponentBuilder
from app.services.simulation.historical_master_decision_engine import HistoricalMasterDecisionEngine
from app.services.institutional.institutional_money_score_engine import InstitutionalMoneyScoreEngine
from app.services.reliability_governor_engine import ReliabilityGovernorEngine


class SimulationOrchestratorEngine:
    """
    Coordinates no-lookahead replay with GreyLine decision components.

    Current version:
    - advances simulated time
    - records replay snapshots
    - runs institutional scoring on candidate context
    - keeps future outcome hidden
    """

    def run(
        self,
        symbol="QQQ",
        start_date="2024-01-01",
        end_date="2024-01-10",
        step_days=1,
        starting_capital=10000,
    ):
        replay = MarketReplayEngine(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            step_days=step_days,
        )

        decisions = []
        open_positions = []
        capital = float(starting_capital)

        try:
            while replay.has_next():
                snapshot = replay.next()
                SimulationClock.enable_simulation(snapshot["timestamp"])

                historical_master_decision = HistoricalMasterDecisionEngine().evaluate(
                    [symbol],
                    snapshot["timestamp"][:10]
                )

                candidate = historical_master_decision.get("top_candidate") or {
                    "candidate_available": False,
                    "result": "REJECT",
                    "composite_score": 0
                }
                if not candidate.get("candidate_available"):
                    candidate = {
                        "symbol": symbol.upper(),
                        "option_type": "UNKNOWN",
                        "adjusted_score": 0,
                        "liquidity_score": 0,
                        "signal_reliability_score": 0,
                        "direction_confidence": 0,
                        "setup_score": 0,
                    }

                # Normalize simulator adapter output to production-style score field.
                if candidate.get("adjusted_score") is None:
                    candidate["adjusted_score"] = candidate.get("composite_score", 0)

                institutional = InstitutionalMoneyScoreEngine().evaluate(
                    candidate,
                    feeds={
                        "options_flow": {
                            "score": candidate.get("adjusted_score"),
                        },
                        "order_flow": {
                            "score": candidate.get("liquidity_score"),
                        },
                        "institutional_sponsorship": {
                            "score": candidate.get("signal_reliability_score"),
                        },
                    },
                )

                reliability_governor = ReliabilityGovernorEngine().evaluate()

                decision = {
                    "simulated_time": SimulationClock.isoformat(),
                    "reliability_governor": reliability_governor,
                    "reliability_operating_mode": reliability_governor.get("operating_mode"),
                    "reliability_execution_allowed": reliability_governor.get("execution_allowed"),
                    "reliability_new_entries_allowed": reliability_governor.get("new_entries_allowed"),
                    "reliability_autonomous_allowed": reliability_governor.get("autonomous_allowed"),
                    "reliability_score": reliability_governor.get("reliability_score"),
                    "symbol": symbol.upper(),
                    "market_data": snapshot.get("market_data"),
                    "future_visible": False,
                    "decision": (
                        "EXECUTE" if candidate.get("adjusted_score", 0) >= 80
                        else "WATCH" if candidate.get("adjusted_score", 0) >= 55
                        else "OBSERVE"
                    ),
                    "reason": "Replay OHLCV signal evaluated with no future data.",
                    "candidate": candidate,
                    "institutional_money_score": institutional.get("institutional_money_score"),
                    "institutional_flow_mode": institutional.get("flow_mode"),
                    "capital": capital,
                }
                # Execution must obey the adapter's final gated result.
                # This prevents blocked candidates from filling when raw adjusted_score says EXECUTE.
                decision["decision"] = candidate.get("result", decision.get("decision"))

                execution = SimulationExecutionEngine().evaluate(decision, capital)
                capital = execution.get("capital_after", capital)

                position_update = SimulationPositionEngine().update(
                    open_positions,
                    execution,
                    snapshot.get("market_data"),
                )
                open_positions = position_update.get("open_positions", [])

                exit_update = SimulationExitEngine().evaluate(
                    open_positions,
                    snapshot.get("market_data"),
                )
                open_positions = exit_update.get("remaining_open_positions", open_positions)
                realized_pnl = sum(
                    float(x.get("realized_pnl") or 0)
                    for x in exit_update.get("closed_positions", [])
                )
                cash_returned = sum(
                    float(x.get("total_cash_returned") or 0)
                    for x in exit_update.get("closed_positions", [])
                )
                capital = round(capital + cash_returned, 2)

                open_position_value = round(sum(
                    float(pos.get("shares") or 0) * float(pos.get("current_price") or 0)
                    for pos in open_positions
                ), 2)
                equity_value = round(capital + open_position_value, 2)

                closed_positions = exit_update.get("closed_positions", [])

                decision["execution"] = execution
                decision["position_update"] = position_update
                decision["exit_update"] = exit_update
                decision["closed_positions"] = closed_positions
                decision["closed_position_count"] = len(closed_positions)
                decision["exit_event"] = bool(closed_positions)
                decision["realized_pnl"] = round(realized_pnl, 2)
                decision["cash_returned"] = round(cash_returned, 2)
                decision["open_position_value"] = open_position_value
                decision["equity_value"] = equity_value

                outcome_reveal = SimulationOutcomeRevealEngine().evaluate(
                    decision=decision,
                    current_simulated_time=SimulationClock.isoformat(),
                )
                learning = SimulationLearningEngine().evaluate(
                    decision=decision,
                    outcome=outcome_reveal.get("outcome"),
                )
                SimulationOutcomeLedgerEngine().record(outcome_reveal)
                decision["outcome_reveal"] = outcome_reveal
                decision["learning"] = learning

                decisions.append(copy.deepcopy(decision))
                SimulationLedgerEngine().record(copy.deepcopy(decision))
        finally:
            SimulationClock.disable_simulation()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "SimulationOrchestratorEngine",
            "mode": "NO_LOOKAHEAD",
            "symbol": symbol.upper(),
            "start_date": start_date,
            "end_date": end_date,
            "step_days": step_days,
            "starting_capital": float(starting_capital),
            "ending_capital": capital,
            "open_position_count": len(open_positions),
            "open_positions": open_positions,
            "decision_count": len(decisions),
            "decisions": decisions,
            "sample_decisions": decisions[:5],
            "final_decision": decisions[-1] if decisions else None,
            "rules": {
                "simulation_clock_enabled_per_step": True,
                "future_prices_visible": False,
                "future_outcomes_visible": False,
                "production_engine_bridge": "HISTORICAL_MASTER_DECISION_BRIDGE",
            },
            "status": "SIMULATION_ORCHESTRATOR_READY",
        }
