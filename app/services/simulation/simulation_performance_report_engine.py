class SimulationPerformanceReportEngine:
    """
    Summarizes completed simulation performance.
    Reporting only. Does not change trading logic.
    """

    def build(self, simulation_result):
        simulation_result = simulation_result or {}
        decisions = simulation_result.get("decisions") or []

        closed = []
        for d in decisions:
            closed.extend(d.get("closed_positions") or [])

        wins = [p for p in closed if float(p.get("realized_pnl") or 0) > 0]
        losses = [p for p in closed if float(p.get("realized_pnl") or 0) < 0]

        realized_pnl = round(sum(float(p.get("realized_pnl") or 0) for p in closed), 2)
        gross_profit = round(sum(float(p.get("realized_pnl") or 0) for p in wins), 2)
        gross_loss = round(abs(sum(float(p.get("realized_pnl") or 0) for p in losses)), 2)

        trade_count = len(closed)
        win_rate = round((len(wins) / trade_count) * 100, 2) if trade_count else 0
        avg_win = round(gross_profit / len(wins), 2) if wins else 0
        avg_loss = round(gross_loss / len(losses), 2) if losses else 0
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else None
        expectancy = round(realized_pnl / trade_count, 2) if trade_count else 0

        starting_capital = float(simulation_result.get("starting_capital") or 0)
        ending_capital = float(simulation_result.get("ending_capital") or 0)
        open_positions = simulation_result.get("open_positions") or []
        open_position_value = round(sum(
            float(p.get("shares") or 0) * float(p.get("current_price") or 0)
            for p in open_positions
        ), 2)

        total_equity = round(ending_capital + open_position_value, 2)
        return_pct = round(((total_equity - starting_capital) / starting_capital) * 100, 2) if starting_capital else 0

        by_risk_state = {}
        for p_closed in closed:
            risk_state = p_closed.get("risk_state") or "UNKNOWN"
            by_risk_state.setdefault(risk_state, []).append(p_closed)

        risk_state_report = {}
        for risk_state, subset in by_risk_state.items():
            pnl = round(sum(float(p.get("realized_pnl") or 0) for p in subset), 2)
            wins_subset = [p for p in subset if float(p.get("realized_pnl") or 0) > 0]
            risk_state_report[risk_state] = {
                "trade_count": len(subset),
                "winning_trades": len(wins_subset),
                "win_rate_pct": round((len(wins_subset) / len(subset)) * 100, 2) if subset else 0,
                "realized_pnl": pnl,
                "expectancy_per_trade": round(pnl / len(subset), 2) if subset else 0,
            }

        by_regime_score_bucket = {
            "65_to_74_99": [],
            "75_to_84_99": [],
            "85_to_94_99": [],
            "95_plus": [],
            "unknown": [],
        }

        for p_closed in closed:
            score = p_closed.get("regime_score")
            try:
                score = float(score)
            except Exception:
                score = None

            if score is None:
                by_regime_score_bucket["unknown"].append(p_closed)
            elif score >= 95:
                by_regime_score_bucket["95_plus"].append(p_closed)
            elif score >= 85:
                by_regime_score_bucket["85_to_94_99"].append(p_closed)
            elif score >= 75:
                by_regime_score_bucket["75_to_84_99"].append(p_closed)
            elif score >= 65:
                by_regime_score_bucket["65_to_74_99"].append(p_closed)
            else:
                by_regime_score_bucket["unknown"].append(p_closed)

        regime_score_bucket_report = {}
        for bucket, subset in by_regime_score_bucket.items():
            pnl = round(sum(float(p.get("realized_pnl") or 0) for p in subset), 2)
            wins_subset = [p for p in subset if float(p.get("realized_pnl") or 0) > 0]
            regime_score_bucket_report[bucket] = {
                "trade_count": len(subset),
                "winning_trades": len(wins_subset),
                "win_rate_pct": round((len(wins_subset) / len(subset)) * 100, 2) if subset else 0,
                "realized_pnl": pnl,
                "expectancy_per_trade": round(pnl / len(subset), 2) if subset else 0,
            }

        by_regime = {}
        for p_closed in closed:
            regime = p_closed.get("regime") or "UNKNOWN"
            by_regime.setdefault(regime, []).append(p_closed)

        regime_report = {}
        for regime, subset in by_regime.items():
            pnl = round(sum(float(p.get("realized_pnl") or 0) for p in subset), 2)
            wins_subset = [p for p in subset if float(p.get("realized_pnl") or 0) > 0]
            regime_report[regime] = {
                "trade_count": len(subset),
                "winning_trades": len(wins_subset),
                "win_rate_pct": round((len(wins_subset) / len(subset)) * 100, 2) if subset else 0,
                "realized_pnl": pnl,
                "expectancy_per_trade": round(pnl / len(subset), 2) if subset else 0,
            }

        by_exit_reason = {}
        for p_closed in closed:
            reason = p_closed.get("exit_reason") or "UNKNOWN"
            by_exit_reason.setdefault(reason, []).append(p_closed)

        exit_reason_report = {}
        for reason, subset in by_exit_reason.items():
            pnl = round(sum(float(p.get("realized_pnl") or 0) for p in subset), 2)
            wins_subset = [p for p in subset if float(p.get("realized_pnl") or 0) > 0]
            exit_reason_report[reason] = {
                "trade_count": len(subset),
                "winning_trades": len(wins_subset),
                "win_rate_pct": round((len(wins_subset) / len(subset)) * 100, 2) if subset else 0,
                "realized_pnl": pnl,
                "expectancy_per_trade": round(pnl / len(subset), 2) if subset else 0,
            }

        by_exit_reason = {}
        for p_closed in closed:
            reason = p_closed.get("exit_reason") or "UNKNOWN"
            by_exit_reason.setdefault(reason, []).append(p_closed)

        exit_reason_report = {}
        for reason, subset in by_exit_reason.items():
            pnl = round(sum(float(p.get("realized_pnl") or 0) for p in subset), 2)
            wins_subset = [p for p in subset if float(p.get("realized_pnl") or 0) > 0]
            exit_reason_report[reason] = {
                "trade_count": len(subset),
                "winning_trades": len(wins_subset),
                "win_rate_pct": round((len(wins_subset) / len(subset)) * 100, 2) if subset else 0,
                "realized_pnl": pnl,
                "expectancy_per_trade": round(pnl / len(subset), 2) if subset else 0,
            }

        by_score_bucket = {
            "85_to_89_99": [],
            "90_to_94_99": [],
            "95_plus": [],
            "unknown": [],
        }

        for p_closed in closed:
            score = p_closed.get("composite_score")
            try:
                score = float(score)
            except Exception:
                score = None

            if score is None:
                by_score_bucket["unknown"].append(p_closed)
            elif score >= 95:
                by_score_bucket["95_plus"].append(p_closed)
            elif score >= 90:
                by_score_bucket["90_to_94_99"].append(p_closed)
            elif score >= 85:
                by_score_bucket["85_to_89_99"].append(p_closed)
            else:
                by_score_bucket["unknown"].append(p_closed)

        score_bucket_report = {}
        for bucket, subset in by_score_bucket.items():
            pnl = round(sum(float(p.get("realized_pnl") or 0) for p in subset), 2)
            wins_subset = [p for p in subset if float(p.get("realized_pnl") or 0) > 0]
            score_bucket_report[bucket] = {
                "trade_count": len(subset),
                "winning_trades": len(wins_subset),
                "win_rate_pct": round((len(wins_subset) / len(subset)) * 100, 2) if subset else 0,
                "realized_pnl": pnl,
                "expectancy_per_trade": round(pnl / len(subset), 2) if subset else 0,
            }

        by_option_type = {}
        for option_type in ["CALL", "PUT"]:
            subset = [p for p in closed if p.get("option_type") == option_type]
            pnl = round(sum(float(p.get("realized_pnl") or 0) for p in subset), 2)
            wins_subset = [p for p in subset if float(p.get("realized_pnl") or 0) > 0]
            by_option_type[option_type] = {
                "trade_count": len(subset),
                "winning_trades": len(wins_subset),
                "win_rate_pct": round((len(wins_subset) / len(subset)) * 100, 2) if subset else 0,
                "realized_pnl": pnl,
                "expectancy_per_trade": round(pnl / len(subset), 2) if subset else 0,
            }

        return {
            "engine": "SimulationPerformanceReportEngine",
            "trade_count": trade_count,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate_pct": win_rate,
            "realized_pnl": realized_pnl,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "average_winner": avg_win,
            "average_loser": avg_loss,
            "profit_factor": profit_factor,
            "expectancy_per_trade": expectancy,
            "starting_capital": starting_capital,
            "ending_cash": ending_capital,
            "open_position_count": len(open_positions),
            "open_position_value": open_position_value,
            "total_equity": total_equity,
            "return_pct": return_pct,
            "performance_by_option_type": by_option_type,
            "performance_by_score_bucket": score_bucket_report,
            "performance_by_exit_reason": exit_reason_report,
            "performance_by_regime": regime_report,
            "performance_by_regime_score_bucket": regime_score_bucket_report,
            "performance_by_risk_state": risk_state_report,
            "performance_by_exit_reason": exit_reason_report,
            "status": "SIMULATION_PERFORMANCE_REPORT_READY",
        }
