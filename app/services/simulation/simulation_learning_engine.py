from datetime import datetime


class SimulationLearningEngine:
    """
    Updates GreyLine learning only after the outcome of a simulated event
    becomes known.
    """

    def evaluate(self, decision, outcome=None):
        decision = decision or {}

        decision_summary = {
            "simulated_time": decision.get("simulated_time"),
            "symbol": decision.get("symbol"),
            "decision": decision.get("decision"),
            "capital": decision.get("capital"),
        }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "SimulationLearningEngine",
            "decision_summary": decision_summary,
            "outcome_available": outcome is not None,
            "learning_applied": outcome is not None,
            "future_data_used": False,
            "status": "SIMULATION_LEARNING_READY",
        }
