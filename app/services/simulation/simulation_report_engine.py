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

        realized_pnl = round(sum(float(r.get("realized_pnl") or 0) for r in rows), 2)
        execute_count = decisions.get("EXECUTE", 0)
        closed_trade_count = sum(
            int(((r.get("exit_update") or {}).get("closed_count")) or 0)
            for r in rows
        )

        starting_capital = first.get("capital") if first else None
        latest_capital = latest.get("capital") if latest else None
        return_pct = None
        if starting_capital:
            return_pct = round((realized_pnl / float(starting_capital)) * 100, 2)

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
            "execute_count": execute_count,
            "closed_trade_count": closed_trade_count,
            "status": "SIMULATION_REPORT_READY",
        }
