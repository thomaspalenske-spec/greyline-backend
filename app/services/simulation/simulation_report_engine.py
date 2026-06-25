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

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "SimulationReportEngine",
            "records": len(rows),
            "first_simulated_time": first.get("simulated_time") if first else None,
            "latest_simulated_time": latest.get("simulated_time") if latest else None,
            "decision_counts": decisions,
            "symbol_counts": symbols,
            "future_visible_violations": len([r for r in rows if r.get("future_visible") is not False]),
            "starting_capital": first.get("capital") if first else None,
            "latest_capital": latest.get("capital") if latest else None,
            "status": "SIMULATION_REPORT_READY",
        }
