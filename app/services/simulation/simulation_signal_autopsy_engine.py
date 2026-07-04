class SimulationSignalAutopsyEngine:
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
        "bullish_score",
        "bearish_score",
        "setup_score",
    ]

    def build(self, simulation_result):
        trades = []

        for d in simulation_result.get("decisions") or []:
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

        summary = self._component_summary(winners, losers)

        return {
            "engine": "SimulationSignalAutopsyEngine",
            "trade_count": len(trades),
            "winner_count": len(winners),
            "loser_count": len(losers),
            "confidence": self._confidence(len(trades), len(winners), len(losers)),
            "component_summary": summary,
            "predictive_components": self._predictive_components(summary),
            "recommended_thresholds": self._recommended_thresholds(winners),
            "trades": trades,
            "blocked_execute_candidates": self._blocked_execute_candidates(simulation_result),
            "status": "SIMULATION_SIGNAL_AUTOPSY_READY",
        }


    def _blocked_execute_candidates(self, simulation_result):
        blocked = []
        for d in simulation_result.get("decisions") or []:
            c = d.get("candidate") or {}
            blockers = c.get("execution_blockers") or []

            if not blockers:
                continue

            if c.get("option_type") != "CALL":
                continue

            near_execute = (
                float(c.get("composite_score") or 0) >= 85
                and float(c.get("institutional_sponsorship_score") or 0) >= 80
            )
            if not near_execute:
                continue

            row = {
                "simulated_time": d.get("simulated_time"),
                "symbol": c.get("symbol"),
                "result": c.get("result"),
                "option_type": c.get("option_type"),
                "directional_bias": c.get("directional_bias"),
                "execution_blockers": blockers,
            }

            for k in self.COMPONENT_KEYS:
                row[k] = c.get(k)

            blocked.append(row)

        return blocked

    def _values(self, rows, key):
        vals = []
        for r in rows:
            v = r.get(key)
            if isinstance(v, (int, float)):
                vals.append(float(v))
        return vals

    def _avg(self, rows, key):
        vals = self._values(rows, key)
        return round(sum(vals) / len(vals), 2) if vals else 0

    def _min(self, rows, key):
        vals = self._values(rows, key)
        return round(min(vals), 2) if vals else 0

    def _component_summary(self, winners, losers):
        out = {}
        for k in self.COMPONENT_KEYS:
            winner_avg = self._avg(winners, k)
            loser_avg = self._avg(losers, k)
            spread = round(winner_avg - loser_avg, 2)

            out[k] = {
                "winner_avg": winner_avg,
                "loser_avg": loser_avg,
                "spread": spread,
                "absolute_spread": abs(spread),
                "winner_min": self._min(winners, k),
                "loser_min": self._min(losers, k),
            }
        return out

    def _predictive_components(self, summary):
        rows = []
        for k, v in summary.items():
            rows.append({
                "component": k,
                "winner_avg": v.get("winner_avg"),
                "loser_avg": v.get("loser_avg"),
                "spread": v.get("spread"),
                "absolute_spread": v.get("absolute_spread"),
            })
        return sorted(rows, key=lambda x: x["absolute_spread"], reverse=True)

    def _recommended_thresholds(self, winners):
        return {
            k: self._min(winners, k)
            for k in self.COMPONENT_KEYS
            if self._min(winners, k) > 0
        }

    def _confidence(self, trade_count, winner_count, loser_count):
        if trade_count >= 30:
            level = "HIGH"
        elif trade_count >= 10:
            level = "MEDIUM"
        else:
            level = "LOW"

        return {
            "trade_count": trade_count,
            "winner_sample_size": winner_count,
            "loser_sample_size": loser_count,
            "confidence": level,
        }
