class SimulationExpectedValueReportEngine:
    """
    Historical EV report from completed simulation trades.
    Reporting only. Does not change execution logic.
    """

    def build(self, simulation_result):
        simulation_result = simulation_result or {}
        decisions = simulation_result.get("decisions") or []

        closed = []
        for d in decisions:
            closed.extend(d.get("closed_positions") or [])

        groups = {
            "ALL": closed,
            "CALL": [p for p in closed if p.get("option_type") == "CALL"],
            "PUT": [p for p in closed if p.get("option_type") == "PUT"],
        }

        report = {}
        for name, trades in groups.items():
            report[name] = self._summarize(trades)

        return {
            "engine": "SimulationExpectedValueReportEngine",
            "trade_count": len(closed),
            "expected_value": report,
            "status": "SIMULATION_EXPECTED_VALUE_REPORT_READY",
        }

    def _summarize(self, trades):
        trades = trades or []
        wins = [t for t in trades if float(t.get("realized_pnl") or 0) > 0]
        losses = [t for t in trades if float(t.get("realized_pnl") or 0) < 0]

        trade_count = len(trades)
        win_rate = (len(wins) / trade_count) if trade_count else 0

        avg_win = (
            sum(float(t.get("realized_pnl") or 0) for t in wins) / len(wins)
            if wins else 0
        )
        avg_loss = (
            abs(sum(float(t.get("realized_pnl") or 0) for t in losses) / len(losses))
            if losses else 0
        )

        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        return {
            "trade_count": trade_count,
            "win_probability_pct": round(win_rate * 100, 2),
            "loss_probability_pct": round((1 - win_rate) * 100, 2) if trade_count else 0,
            "average_win": round(avg_win, 2),
            "average_loss": round(avg_loss, 2),
            "expected_value_per_trade": round(expectancy, 2),
        }
