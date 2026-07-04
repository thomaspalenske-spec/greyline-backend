class SimulationPutLearningReportEngine:
    BUCKETS = [
        ("under_60", 0, 60),
        ("60_to_64_99", 60, 65),
        ("65_to_69_99", 65, 70),
        ("70_to_74_99", 70, 75),
        ("75_to_79_99", 75, 80),
        ("80_plus", 80, 101),
    ]

    def build(self, simulation_result):
        rows = {name: {
            "closed_trade_count": 0,
            "wins": 0,
            "losses": 0,
            "realized_pnl": 0.0,
            "avg_pnl": 0.0,
            "win_rate_pct": 0.0,
            "blocked_put_candidates": 0,
            "near_execute_put_candidates": 0,
        } for name, _, _ in self.BUCKETS}

        for d in simulation_result.get("decisions", []) or []:
            c = d.get("candidate") or {}
            if str(c.get("option_type")).upper() == "PUT":
                risk = self._num(c.get("risk_state_score"))
                bucket = self._bucket(risk)
                rows[bucket]["blocked_put_candidates"] += 1

                if (c.get("composite_score") or 0) >= 85:
                    rows[bucket]["near_execute_put_candidates"] += 1

            for pos in d.get("closed_positions", []) or []:
                if str(pos.get("option_type")).upper() != "PUT":
                    continue

                risk = self._num(pos.get("risk_state_score"))
                pnl = self._num(pos.get("realized_pnl")) or 0.0
                bucket = self._bucket(risk)

                row = rows[bucket]
                row["closed_trade_count"] += 1
                row["realized_pnl"] += pnl
                if pnl > 0:
                    row["wins"] += 1
                elif pnl < 0:
                    row["losses"] += 1

        for row in rows.values():
            n = row["closed_trade_count"]
            if n:
                row["realized_pnl"] = round(row["realized_pnl"], 2)
                row["avg_pnl"] = round(row["realized_pnl"] / n, 2)
                row["win_rate_pct"] = round((row["wins"] / n) * 100, 2)

        return {
            "engine": "SimulationPutLearningReportEngine",
            "put_learning_by_risk_bucket": rows,
            "status": "SIMULATION_PUT_LEARNING_REPORT_READY",
        }

    def _bucket(self, risk):
        if risk is None:
            return "under_60"
        for name, lo, hi in self.BUCKETS:
            if lo <= risk < hi:
                return name
        return "80_plus"

    @staticmethod
    def _num(v):
        try:
            return float(v) if v not in [None, ""] else None
        except Exception:
            return None
