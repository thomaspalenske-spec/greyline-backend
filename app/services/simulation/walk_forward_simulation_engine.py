from datetime import datetime, timedelta


class WalkForwardSimulationEngine:
    """
    No-lookahead simulation shell.

    This engine intentionally does not use future market data.
    First version creates the simulation scaffold and lifecycle report.
    """

    def run(
        self,
        symbol="QQQ",
        start_date="2024-01-01",
        end_date="2024-12-31",
        step_days=1,
        starting_capital=10000,
    ):
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        if end <= start:
            return {
                "status": "WALK_FORWARD_SIMULATION_INVALID_RANGE",
                "error": "end_date must be after start_date",
            }

        steps = []
        cursor = start

        while cursor <= end:
            steps.append({
                "simulated_time": cursor.date().isoformat(),
                "symbol": symbol.upper(),
                "lookahead_allowed": False,
                "decision": "OBSERVE",
                "reason": "Simulation scaffold ready; market replay data not connected yet.",
            })
            cursor += timedelta(days=step_days)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "WalkForwardSimulationEngine",
            "mode": "NO_LOOKAHEAD",
            "symbol": symbol.upper(),
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "step_days": step_days,
            "starting_capital": starting_capital,
            "ending_capital": starting_capital,
            "total_steps": len(steps),
            "sample_steps": steps[:5],
            "final_step": steps[-1] if steps else None,
            "rules": {
                "future_prices_visible": False,
                "future_volatility_visible": False,
                "future_outcomes_visible": False,
                "learning_updates_after_outcome_only": True,
            },
            "status": "WALK_FORWARD_SIMULATION_READY",
        }
