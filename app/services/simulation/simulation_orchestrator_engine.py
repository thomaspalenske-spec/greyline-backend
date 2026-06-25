from datetime import datetime

from app.services.simulation.simulation_clock import SimulationClock
from app.services.simulation.simulation_ledger_engine import SimulationLedgerEngine
from app.services.simulation.simulation_learning_engine import SimulationLearningEngine
from app.services.simulation.simulation_outcome_reveal_engine import SimulationOutcomeRevealEngine
from app.services.simulation.market_replay_engine import MarketReplayEngine
from app.services.institutional.institutional_money_score_engine import InstitutionalMoneyScoreEngine


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
        capital = float(starting_capital)

        try:
            while replay.has_next():
                snapshot = replay.next()
                SimulationClock.enable_simulation(snapshot["timestamp"])

                candidate = {
                    "symbol": symbol.upper(),
                    "option_type": "CALL",
                    "adjusted_score": 0,
                    "liquidity_score": 0,
                    "signal_reliability_score": 0,
                    "direction_confidence": 0,
                    "setup_score": 0,
                }

                institutional = InstitutionalMoneyScoreEngine().evaluate(candidate)

                decision = {
                    "simulated_time": SimulationClock.isoformat(),
                    "symbol": symbol.upper(),
                    "future_visible": False,
                    "decision": "OBSERVE",
                    "reason": "Production replay scaffold active; historical market state not connected yet.",
                    "institutional_money_score": institutional.get("institutional_money_score"),
                    "institutional_flow_mode": institutional.get("flow_mode"),
                    "capital": capital,
                }
                outcome_reveal = SimulationOutcomeRevealEngine().evaluate(
                    decision=decision,
                    current_simulated_time=SimulationClock.isoformat(),
                )
                learning = SimulationLearningEngine().evaluate(
                    decision=decision,
                    outcome=outcome_reveal.get("outcome"),
                )
                decision["outcome_reveal"] = outcome_reveal
                decision["learning"] = learning

                decisions.append(decision)
                SimulationLedgerEngine().record(decision)
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
            "decision_count": len(decisions),
            "sample_decisions": decisions[:5],
            "final_decision": decisions[-1] if decisions else None,
            "rules": {
                "simulation_clock_enabled_per_step": True,
                "future_prices_visible": False,
                "future_outcomes_visible": False,
                "production_engine_bridge": "PARTIAL",
            },
            "status": "SIMULATION_ORCHESTRATOR_READY",
        }
