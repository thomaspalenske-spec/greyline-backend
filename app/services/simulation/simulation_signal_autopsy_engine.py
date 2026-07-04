class SimulationSignalAutopsyEngine:
    """
    Builds a trade-level autopsy from simulation output.
    Focus: explain every closed EXECUTE signal and compare winners vs losers.
    """

    COMPONENT_KEYS = [
        "composite_score",
        "institutional_sponsorship_score",
        "regime_score",
        "risk_state_score",
        "trend_persistence_score",
        "breadth_score",
        "asymmetry_score",
        "volatility_score",
        "expected_value_score",
        "direction_confidence",
        "historical_execution_bonus",
    ]

    def build(self, simulation_result):
        decisions = simulation_result.get("decisions") or []
        trades = []

        for d in decisions:
            exit_time = d.get("simulated_time")
            for p in d.get("closed_positions") or []:
                pnl = float(p.get("realized_pnl") or 0)

                trade = {
                    "entry_time": p.get("entry_time"),
                    "exit_time": exit_time,
                    "symbol": p.get("symbol"),
                    "option_type": p.get("option_type"),
                    "direction": p.get("direction"),
                    "result": "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT",
                    "realized_pnl": round(pnl, 2),
                    "exit_reason": p.get("exit_reason"),
                }

                for k in self.COMPONENT_KEYS:
                    trade[k] = p.get(k)

                trades.append(trade)

        winners = [t for t in trades if t["result"] == "WIN"]
        losers = [t for t in trades if t["result"] == "LOSS"]

        return {
            "engine": "SimulationSignalAutopsyEngine",
            "trade_count": len(trades),
            "winner_count": len(winners),
            "loser_count": len(losers),
            "component_summary": self._component_summary(winners, losers),
            "trades": trades,
            "status": "SIMULATION_SIGNAL_AUTOPSY_READY",
        }

    def _avg(self, rows, key):
        vals = []
        for r in rows:
            v = r.get(key)
            if isinstance(v, (int, float)):
                vals.append(float(v))
        return round(sum(vals) / len(vals), 2) if vals else 0

    def _component_summary(self, winners, losers):
        out = {}
        for k in self.COMPONENT_KEYS:
            out[k] = {
                "winner_avg": self._avg(winners, k),
                "loser_avg": self._avg(losers, k),
                "spread": round(self._avg(winners, k) - self._avg(losers, k), 2),
            }
        return out
