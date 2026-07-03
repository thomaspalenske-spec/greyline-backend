class SimulationInstitutionalFlowReportEngine:
    """
    Analyze historical performance versus institutional sponsorship score.
    """

    def build(self, simulation_result):
        simulation_result = simulation_result or {}

        closed = []
        for d in simulation_result.get("decisions") or []:
            closed.extend(d.get("closed_positions") or [])

        buckets = {
            "under_70": [],
            "70_to_79_99": [],
            "80_to_89_99": [],
            "90_plus": [],
            "unknown": [],
        }

        for p in closed:
            score = p.get("institutional_sponsorship_score")

            if score is None:
                buckets["unknown"].append(p)
            elif score < 70:
                buckets["under_70"].append(p)
            elif score < 80:
                buckets["70_to_79_99"].append(p)
            elif score < 90:
                buckets["80_to_89_99"].append(p)
            else:
                buckets["90_plus"].append(p)

        report = {}

        for name, trades in buckets.items():
            wins = [t for t in trades if float(t.get("realized_pnl") or 0) > 0]
            pnl = sum(float(t.get("realized_pnl") or 0) for t in trades)

            report[name] = {
                "trade_count": len(trades),
                "winning_trades": len(wins),
                "win_rate_pct": round(
                    len(wins) / len(trades) * 100, 2
                ) if trades else 0,
                "realized_pnl": round(pnl, 2),
                "expectancy_per_trade": round(
                    pnl / len(trades), 2
                ) if trades else 0,
            }

        return {
            "engine": "SimulationInstitutionalFlowReportEngine",
            "performance_by_institutional_score": report,
            "status": "SIMULATION_INSTITUTIONAL_FLOW_REPORT_READY",
        }
