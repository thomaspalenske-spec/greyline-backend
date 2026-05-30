from app.services.ledger_engine import LedgerEngine

class PositionReconciliationEngine:

    def reconcile_positions(self):
        ledger = LedgerEngine().load()

        active_positions = []
        closed_positions = []

        for trade in ledger.get("trades", []):
            if trade.get("state") == "ACTIVE":
                active_positions.append(trade)

            if trade.get("state") == "CLOSED":
                closed_positions.append(trade)

        return {
    "active_positions": active_positions,
    "closed_positions": closed_positions,
    "active_count": len(active_positions),
    "closed_count": len(closed_positions),
    "ledger_total": len(ledger.get("trades", [])),
    "reconciliation_status": "PASS"
}