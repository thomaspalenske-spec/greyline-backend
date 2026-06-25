from datetime import datetime

from app.services.simulation.simulation_ledger_engine import SimulationLedgerEngine


class SimulationReportEngine:
    def evaluate(self, limit=10000):
        rows = SimulationLedgerEngine().load(limit=limit)

        decisions = {}
        symbols = {}

        for row in rows:
            decision = row.get("decision") or "UNKNOWN"
            symbol = row.get("symbol") or "UNKNOWN"

            decisions[decision] = decisions.get(decision, 0) + 1
            symbols[symbol] = symbols.get(symbol, 0) + 1

        first = rows[0] if rows else None
        latest = rows[-1] if rows else None

        closed_positions = []
        for r in rows:
            closed_positions.extend((r.get("exit_update") or {}).get("closed_positions") or [])

        realized_pnl = round(sum(float(r.get("realized_pnl") or 0) for r in rows), 2)
        execute_count = decisions.get("EXECUTE", 0)
        closed_trade_count = len(closed_positions)
        winning_trades = len([p for p in closed_positions if float(p.get("realized_pnl") or 0) > 0])
        losing_trades = len([p for p in closed_positions if float(p.get("realized_pnl") or 0) < 0])
        win_rate = round((winning_trades / closed_trade_count) * 100, 2) if closed_trade_count else None
        gross_profit = round(sum(float(p.get("realized_pnl") or 0) for p in closed_positions if float(p.get("realized_pnl") or 0) > 0), 2)
        gross_loss = round(abs(sum(float(p.get("realized_pnl") or 0) for p in closed_positions if float(p.get("realized_pnl") or 0) < 0)), 2)
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else None
        average_win = round(gross_profit / winning_trades, 2) if winning_trades else None
        average_loss = round(gross_loss / losing_trades, 2) if losing_trades else None

        starting_capital = first.get("capital") if first else None
        latest_capital = latest.get("capital") if latest else None
        return_pct = None
        if starting_capital:
            return_pct = round((realized_pnl / float(starting_capital)) * 100, 2)

        equity_curve_rows = [
            {
                "simulated_time": r.get("simulated_time"),
                "equity_value": float(r.get("equity_value") if r.get("equity_value") is not None else r.get("capital") or 0),
            }
            for r in rows
            if r.get("equity_value") is not None or r.get("capital") is not None
        ]
        equity_curve = [r["equity_value"] for r in equity_curve_rows]
        peak = None
        max_drawdown = 0
        max_drawdown_pct = 0

        for equity in equity_curve:
            peak = equity if peak is None else max(peak, equity)
            drawdown = peak - equity
            drawdown_pct = (drawdown / peak) * 100 if peak else 0

            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = drawdown_pct

        max_drawdown = round(max_drawdown, 2)
        max_drawdown_pct = round(max_drawdown_pct, 2)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "SimulationReportEngine",
            "records": len(rows),
            "first_simulated_time": first.get("simulated_time") if first else None,
            "latest_simulated_time": latest.get("simulated_time") if latest else None,
            "decision_counts": decisions,
            "symbol_counts": symbols,
            "future_visible_violations": len([r for r in rows if r.get("future_visible") is not False]),
            "starting_capital": starting_capital,
            "latest_capital": latest_capital,
            "realized_pnl": realized_pnl,
            "return_pct": return_pct,
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown_pct,
            "equity_curve": equity_curve_rows,
            "execute_count": execute_count,
            "closed_trade_count": closed_trade_count,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "profit_factor": profit_factor,
            "average_win": average_win,
            "average_loss": average_loss,
            "status": "SIMULATION_REPORT_READY",
        }
