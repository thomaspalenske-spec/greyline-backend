from datetime import datetime, timedelta


class SimulationOutcomeRevealEngine:
    """
    Reveals outcomes only after simulated time has advanced.

    Current version:
    - placeholder outcome
    - enforces no-lookahead rule
    """

    def evaluate(self, decision, current_simulated_time, reveal_after_days=1):
        if isinstance(current_simulated_time, str):
            current_simulated_time = datetime.fromisoformat(current_simulated_time)

        reveal_time = current_simulated_time + timedelta(days=reveal_after_days)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "SimulationOutcomeRevealEngine",
            "decision_time": current_simulated_time.isoformat(),
            "reveal_time": reveal_time.isoformat(),
            "outcome_available_now": False,
            "outcome": None,
            "future_data_used": False,
            "status": "SIMULATION_OUTCOME_REVEAL_READY",
        }
